from kivy.config import Config
Config.set('graphics', 'width', '400')
Config.set('graphics', 'height', '750')
Config.set('graphics', 'resizable', '0')

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.clock import Clock

import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter
from kivy_garden.matplotlib.backend_kivyagg import FigureCanvasKivyAgg

import threading
import time
import ssl

ssl._create_default_https_context = ssl._create_unverified_context

# ==============================================================================
# إعدادات cTrader الحقيقية
# ==============================================================================
SYMBOL = "XAUUSD"  
CTRADER_CLIENT_ID = "35261_ED1ce0k6WWRurTG1vwmkR70lqSufE6nX1bEgDXzgHUzR5dX1wN"
CTRADER_SECRET = "TbZ2SFvUWcR7MIdNhItJzSIKZwSx2v2xe8VIAE0B2Hs3gDKAAe"
CTRADER_TOKEN = "4WyM2a0nY5ZOB7SSKKo_-OBWssNjbbm58hWrlH-W8fs"
CTRADER_ACCOUNT_ID = 48196950  
INITIAL_BALANCE = 103029.90

live_data = {
    "status": "CONNECTING 🟡",
    "price": "0.00",
    "balance": INITIAL_BALANCE,
    "pnl": "+$0.00",
    "signal": "WAITING FOR CRT SETUP...",
    "entry": "----",
    "sl": "----",
    "tp": "----",
    "history": []
}

TEXT_SUB = (0.54, 0.58, 0.62, 1)      
COLOR_GREEN = (0.03, 0.6, 0.5, 1)  
COLOR_RED = (0.95, 0.21, 0.27, 1)  
COLOR_BLUE = (0.1, 0.4, 0.8, 1)

try:
    from twisted.internet import reactor
    from ctrader_open_api import Client, TcpProtocol, EndPoints
    from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *
    from ctrader_open_api.messages.OpenApiMessages_pb2 import *
    from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *
    HAS_CTRADER = True
except Exception:
    HAS_CTRADER = False

class CRTStrategyEngine:
    """ محرك استراتيجية CRT (Setup B: 4H Bias + 15M Sweep & 50% TP) """
    def __init__(self):
        self.htf_bias = "NEUTRAL"  # BULLISH أو BEARISH بناءً على 4H
        self.crt_high = 0.0
        self.crt_low = 0.0
        self.tp_50 = 0.0
        self.state = "WAITING_SWEEP" # WAITING_CRT -> WAITING_SWEEP -> READY_ENTRY

    def analyze_4h_bias(self, candles_4h):
        if len(candles_4h) < 2:
            return
        last_candle = candles_4h[-1]
        if last_candle['close'] > last_candle['open']:
            self.htf_bias = "BULLISH"
        else:
            self.htf_bias = "BEARISH"

    def set_crt_candle(self, candle_1h_or_4h):
        """ تحديد شمعة CRT وحساب هدف 50% الثابت """
        self.crt_high = candle_1h_or_4h['high']
        self.crt_low = candle_1h_or_4h['low']
        self.tp_50 = self.crt_low + (self.crt_high - self.crt_low) / 2.0
        self.state = "WAITING_SWEEP"

    def check_sweep_and_execution(self, current_price, current_candle_15m):
        """ مراقبة الـ Sweep وتحديد SL بدقة على الـ Sweep مباشرة """
        if self.state != "WAITING_SWEEP":
            return None

        # Setup BUY: السياق صاعد، والسعر كسر CRT Low (Sweep) ثم رجع للداخل
        if self.htf_bias == "BULLISH":
            if current_candle_15m['low'] < self.crt_low and current_price > self.crt_low:
                sl = current_candle_15m['low']  # SL محطوط تماماً على الـ Sweep Low
                tp = self.tp_50                 # الهدف 50% الثابت
                self.state = "WAITING_CRT"            
                return {
                    "action": "BUY",
                    "entry": current_price,
                    "sl": sl,
                    "tp": tp
                }

        # Setup SELL: السياق هابط، والسعر كسر CRT High (Sweep) ثم رجع للداخل
        elif self.htf_bias == "BEARISH":
            if current_candle_15m['high'] > self.crt_high and current_price < self.crt_high:
                sl = current_candle_15m['high'] # SL محطوط تماماً على الـ Sweep High
                tp = self.tp_50                 # الهدف 50% الثابت
                self.state = "WAITING_CRT"
                return {
                    "action": "SELL",
                    "entry": current_price,
                    "sl": sl,
                    "tp": tp
                }

        return None


class CTraderEngine(threading.Thread):
    def __init__(self, app):
        super().__init__(daemon=True)
        self.app = app
        self.symbol_id = None
        self.symbol_digits = 5
        self.client = None
        self.strategy = CRTStrategyEngine()

    def run(self):
        if not HAS_CTRADER: return

        def on_connected(client):
            try:
                req = ProtoOAApplicationAuthReq()
                req.clientId = CTRADER_CLIENT_ID
                req.clientSecret = CTRADER_SECRET
                client.send(req)
            except Exception: pass

        def on_disconnected(client, reason):
            live_data["status"] = "DISCONNECTED 🔴"
            Clock.schedule_once(lambda dt: self.app.update_ui_from_live_data(), 0)

        def on_message(client, message):
            try:
                if message.payloadType == 2101:
                    req = ProtoOAAccountAuthReq()
                    req.ctidTraderAccountId = CTRADER_ACCOUNT_ID
                    req.accessToken = CTRADER_TOKEN
                    client.send(req)
                elif message.payloadType == 2103:
                    req = ProtoOASymbolsListReq()
                    req.ctidTraderAccountId = CTRADER_ACCOUNT_ID
                    client.send(req)
                elif message.payloadType == 2115:
                    res = ProtoOASymbolsListRes()
                    res.ParseFromString(message.payload)
                    for symbol in res.symbol:
                        if symbol.symbolName == SYMBOL:
                            self.symbol_id = symbol.symbolId
                            self.symbol_digits = symbol.digits if hasattr(symbol, 'digits') else 5
                            break
                    if self.symbol_id:
                        req_spot = ProtoOASubscribeSpotsReq()
                        req_spot.ctidTraderAccountId = CTRADER_ACCOUNT_ID
                        req_spot.symbolId.append(self.symbol_id)
                        client.send(req_spot)
                        
                        req_bars = ProtoOAGetTrendbarsReq()
                        req_bars.ctidTraderAccountId = CTRADER_ACCOUNT_ID
                        req_bars.symbolId = self.symbol_id
                        req_bars.period = ProtoOATrendbarPeriod.M1
                        req_bars.count = 40
                        client.send(req_bars)

                        live_data["status"] = "CONNECTED 🟢"
                        Clock.schedule_once(lambda dt: self.app.update_ui_from_live_data(), 0)

                elif message.payloadType == 2138:
                    res_bars = ProtoOAGetTrendbarsRes()
                    res_bars.ParseFromString(message.payload)
                    historical_candles = []
                    divider = 10 ** self.symbol_digits
                    
                    for bar in res_bars.trendbar:
                        o = (bar.low + bar.deltaOpen) / divider if hasattr(bar, 'deltaOpen') else bar.low / divider
                        h = (bar.low + bar.deltaHigh) / divider if hasattr(bar, 'deltaHigh') else bar.high / divider
                        l = bar.low / divider
                        c = (bar.low + bar.deltaClose) / divider if hasattr(bar, 'deltaClose') else (bar.low + bar.high)/2 / divider
                        
                        historical_candles.append({
                            'open': o, 'high': h, 'low': l, 'close': c, 'ticks': 10
                        })
                    
                    if historical_candles:
                        self.strategy.analyze_4h_bias(historical_candles)
                        self.strategy.set_crt_candle(historical_candles[-2] if len(historical_candles) > 1 else historical_candles[0])
                        Clock.schedule_once(lambda dt: self.app.load_historical_candles(historical_candles), 0)

                elif message.payloadType == 2131:
                    event = ProtoOASpotEvent()
                    event.ParseFromString(message.payload)
                    divider = 10 ** self.symbol_digits
                    if getattr(event, 'bid', 0) > 0:
                        price = float(event.bid / divider)
                        live_data["price"] = f"{price:.2f}"
                        
                        if self.app.current_candle:
                            signal = self.strategy.check_sweep_and_execution(price, self.app.current_candle)
                            if signal:
                                live_data["signal"] = f"{signal['action']} (CRT 50% TP)"
                                live_data["entry"] = f"{signal['entry']:.2f}"
                                live_data["sl"] = f"{signal['sl']:.2f}"
                                live_data["tp"] = f"{signal['tp']:.2f}"
                                Clock.schedule_once(lambda dt: self.app.update_ui_from_live_data(), 0)

                        Clock.schedule_once(lambda dt: self.app.update_live_price(price), 0)
            except Exception as e: 
                print("Error:", e)

        def send_heartbeat():
            try:
                if self.client: self.client.send(ProtoHeartbeatEvent())
            except: pass
            reactor.callLater(10, send_heartbeat)

        while True:
            try:
                host = EndPoints.PROTOBUF_DEMO_HOST
                port = EndPoints.PROTOBUF_PORT
                self.client = Client(host, port, TcpProtocol)
                self.client.setConnectedCallback(on_connected)
                self.client.setDisconnectedCallback(on_disconnected)
                self.client.setMessageReceivedCallback(on_message)
                self.client.startService()
                reactor.callLater(10, send_heartbeat)
                if not reactor.running:
                    reactor.run(installSignalHandlers=False)
                break
            except Exception:
                time.sleep(5)

class TudaMobileApp(App):
    def build(self):
        self.title = "TUDA AI - CRT Strategy Live"
        self.candles = []
        self.current_candle = None
        self.current_timeframe = 'M1'
        self.last_draw_time = 0 

        root = BoxLayout(orientation='vertical', padding=0, spacing=0)
        
        top_bar = BoxLayout(orientation='vertical', size_hint_y=None, height=100, padding=[10, 5, 10, 5])
        
        row1 = BoxLayout(orientation='horizontal')
        symbol_lbl = Label(text=f"[b]{SYMBOL}[/b] | CRT Strategy", markup=True, color=(1,1,1,1), font_size=16, halign='left')
        symbol_lbl.bind(size=symbol_lbl.setter('text_size'))
        
        self.status_lbl = Label(text=live_data["status"], color=COLOR_GREEN, bold=True, font_size=10, size_hint_x=None, width=100)
        row1.add_widget(symbol_lbl)
        row1.add_widget(self.status_lbl)
        
        self.price_lbl = Label(text=live_data["price"], font_size=28, bold=True, color=(1,1,1,1), halign='left')
        self.price_lbl.bind(size=self.price_lbl.setter('text_size'))
        
        tf_layout = BoxLayout(orientation='horizontal', size_hint_y=None, height=30, spacing=3)
        self.btn_ticks = Button(text="Ticks", background_color=TEXT_SUB, font_size=11, bold=True)
        self.btn_m1 = Button(text="M1", background_color=COLOR_BLUE, font_size=11, bold=True)
        self.btn_m5 = Button(text="M5", background_color=TEXT_SUB, font_size=11, bold=True)
        self.btn_m15 = Button(text="M15", background_color=TEXT_SUB, font_size=11, bold=True)
        self.btn_h1 = Button(text="1H", background_color=TEXT_SUB, font_size=11, bold=True)
        self.btn_h4 = Button(text="4H", background_color=TEXT_SUB, font_size=11, bold=True)
        
        self.btn_ticks.bind(on_press=lambda x: self.change_tf('Ticks', self.btn_ticks))
        self.btn_m1.bind(on_press=lambda x: self.change_tf('M1', self.btn_m1))
        self.btn_m5.bind(on_press=lambda x: self.change_tf('M5', self.btn_m5))
        self.btn_m15.bind(on_press=lambda x: self.change_tf('M15', self.btn_m15))
        self.btn_h1.bind(on_press=lambda x: self.change_tf('1H', self.btn_h1))
        self.btn_h4.bind(on_press=lambda x: self.change_tf('4H', self.btn_h4))
        
        tf_layout.add_widget(self.btn_ticks)
        tf_layout.add_widget(self.btn_m1)
        tf_layout.add_widget(self.btn_m5)
        tf_layout.add_widget(self.btn_m15)
        tf_layout.add_widget(self.btn_h1)
        tf_layout.add_widget(self.btn_h4)
        
        top_bar.add_widget(row1)
        top_bar.add_widget(self.price_lbl)
        top_bar.add_widget(tf_layout)
        root.add_widget(top_bar)

        chart_card = BoxLayout(orientation='vertical', size_hint_y=0.5, padding=[0, 10, 0, 10])
        self.fig, self.ax = plt.subplots(tight_layout=True)
        self.fig.patch.set_facecolor('#FFFFFF') 
        self.ax.set_facecolor('#FFFFFF')        
        
        self.chart_widget = FigureCanvasKivyAgg(self.fig)
        chart_card.add_widget(self.chart_widget)
        root.add_widget(chart_card)

        bottom_scroll = ScrollView(size_hint_y=0.5, do_scroll_x=False, do_scroll_y=True)
        
        info_box = BoxLayout(orientation='vertical', size_hint_y=None, padding=[25, 20, 25, 20], spacing=30)
        info_box.bind(minimum_height=info_box.setter('height'))
        
        account_card = BoxLayout(orientation='vertical', size_hint_y=None, height=95)
        account_card.add_widget(Label(text="ACCOUNT BALANCE", color=TEXT_SUB, font_size=16, bold=True)) 
        
        self.balance_lbl = Label(text=f"${live_data['balance']:,.2f}", font_size=42, bold=True, color=(1,1,1,1)) 
        self.pnl_lbl = Label(text=f"Today P&L: {live_data['pnl']}", color=COLOR_GREEN, bold=True, font_size=20) 
        
        account_card.add_widget(self.balance_lbl)
        account_card.add_widget(self.pnl_lbl)
        
        signal_card = BoxLayout(orientation='vertical', size_hint_y=None, height=160, spacing=8)
        signal_card.add_widget(Label(text="📈 CRT ACTIVE SIGNAL (TP = 50%)", color=TEXT_SUB, bold=True, font_size=16)) 
        
        self.signal_dir_lbl = Label(text=live_data['signal'], font_size=24, bold=True, color=COLOR_BLUE) 
        self.entry_lbl = Label(text=f"Entry Price: {live_data['entry']}", color=(1,1,1,1), font_size=20) 
        self.sl_lbl = Label(text=f"Stop Loss: {live_data['sl']}", color=COLOR_RED, font_size=20)
        self.tp_lbl = Label(text=f"Take Profit (50%): {live_data['tp']}", color=COLOR_GREEN, font_size=20)

        signal_card.add_widget(self.signal_dir_lbl)
        signal_card.add_widget(self.entry_lbl)
        signal_card.add_widget(self.sl_lbl)
        signal_card.add_widget(self.tp_lbl)
        
        self.history_card = BoxLayout(orientation='vertical', size_hint_y=None, spacing=8)
        self.history_card.bind(minimum_height=self.history_card.setter('height'))
        
        title_history = Label(text="📜 RECENT TRADES HISTORY", color=TEXT_SUB, bold=True, font_size=16, size_hint_y=None, height=30)
        title_history.bind(size=title_history.setter('text_size'))
        self.history_card.add_widget(title_history)
        
        self.no_trades_lbl = Label(text="Waiting for CRT setup...", color=TEXT_SUB, font_size=16, size_hint_y=None, height=30)
        self.history_card.add_widget(self.no_trades_lbl)
        
        info_box.add_widget(account_card)
        info_box.add_widget(signal_card)
        info_box.add_widget(self.history_card)
        
        bottom_scroll.add_widget(info_box)
        root.add_widget(bottom_scroll)

        self.engine = CTraderEngine(app=self)
        self.engine.start()

        return root

    def update_ui_from_live_data(self):
        self.status_lbl.text = live_data["status"]
        self.balance_lbl.text = f"${live_data['balance']:,.2f}"
        self.pnl_lbl.text = f"Today P&L: {live_data['pnl']}"
        self.signal_dir_lbl.text = live_data['signal']
        self.entry_lbl.text = f"Entry Price: {live_data['entry']}"
        self.sl_lbl.text = f"Stop Loss: {live_data['sl']}"
        self.tp_lbl.text = f"Take Profit (50%): {live_data['tp']}"

    def load_historical_candles(self, candles):
        self.candles = candles
        self.redraw_chart()

    def change_tf(self, tf_name, btn_instance):
        self.current_timeframe = tf_name
        self.btn_ticks.background_color = TEXT_SUB
        self.btn_m1.background_color = TEXT_SUB
        self.btn_m5.background_color = TEXT_SUB
        self.btn_m15.background_color = TEXT_SUB
        self.btn_h1.background_color = TEXT_SUB
        self.btn_h4.background_color = TEXT_SUB
        btn_instance.background_color = COLOR_BLUE
        
        self.candles = []
        self.current_candle = None
        self.last_draw_time = 0 
        
        self.ax.clear()
        self.ax.set_facecolor('#FFFFFF')
        self.chart_widget.draw()

    def update_live_price(self, price):
        now = time.time()
        live_data["price"] = f"{price:.2f}"
        
        if self.current_candle is None:
            self.current_candle = {'open': price, 'high': price, 'low': price, 'close': price, 'ticks': 1, 'time_start': now}
        else:
            self.current_candle['high'] = max(self.current_candle['high'], price)
            self.current_candle['low'] = min(self.current_candle['low'], price)
            self.current_candle['close'] = price
            self.current_candle['ticks'] += 1

        close_candle = False
        if self.current_timeframe == 'Ticks' and self.current_candle['ticks'] >= 10:
            close_candle = True
        elif self.current_timeframe == 'M1' and (now - self.current_candle['time_start']) >= 60:
            close_candle = True
        elif self.current_timeframe == 'M5' and (now - self.current_candle['time_start']) >= 300:
            close_candle = True
        elif self.current_timeframe == 'M15' and (now - self.current_candle['time_start']) >= 900:
            close_candle = True
        elif self.current_timeframe == '1H' and (now - self.current_candle['time_start']) >= 3600:
            close_candle = True
        elif self.current_timeframe == '4H' and (now - self.current_candle['time_start']) >= 14400:
            close_candle = True

        if close_candle:
            self.candles.append(self.current_candle)
            self.current_candle = {'open': price, 'high': price, 'low': price, 'close': price, 'ticks': 1, 'time_start': now}
            if len(self.candles) > 40:
                self.candles.pop(0)

        if now - self.last_draw_time < 0.5:
            self.price_lbl.text = live_data["price"]
            return  
            
        self.last_draw_time = now
        self.price_lbl.text = live_data["price"]
        self.redraw_chart()

    def redraw_chart(self):
        self.ax.clear()
        all_candles = self.candles + ([self.current_candle] if self.current_candle else [])
        if not all_candles:
            return

        for i, c in enumerate(all_candles):
            color = '#089981' if c['close'] >= c['open'] else '#F23645'
            self.ax.plot([i, i], [c['low'], c['high']], color=color, linewidth=1.2, zorder=2)
            
            body_bottom = min(c['open'], c['close'])
            body_top = max(c['open'], c['close'])
            body_height = body_top - body_bottom
            if body_height < 0.05: 
                body_height = 0.05
                
            self.ax.bar(i, body_height, bottom=body_bottom, color=color, width=0.6, zorder=3)

        self.ax.set_facecolor('#FFFFFF')
        self.ax.grid(color='#E5E5E5', linestyle='-', linewidth=0.5, zorder=0) 
        self.ax.yaxis.set_major_formatter(FormatStrFormatter('%.2f'))
        self.ax.tick_params(colors='black', labelsize=9)
        
        self.ax.yaxis.tick_right()
        self.ax.yaxis.set_label_position("right")

        self.ax.spines['top'].set_visible(False)
        self.ax.spines['left'].set_visible(False)
        self.ax.spines['bottom'].set_color('#CCCCCC')
        self.ax.spines['right'].set_visible(False)

        min_p = min(c['low'] for c in all_candles)
        max_p = max(c['high'] for c in all_candles)
        price_range = max_p - min_p
        
        if price_range < 4.0:
            center_price = (max_p + min_p) / 2.0
            min_p = center_price - 2.0
            max_p = center_price + 2.0
            margin = 0.5
        else:
            margin = price_range * 0.15
            
        self.ax.set_ylim(min_p - margin, max_p + margin)
        
        max_x = max(20, len(all_candles))
        self.ax.set_xlim(-1, max_x)
        
        if self.current_candle:
            line_color = '#089981' if float(live_data["price"]) >= self.current_candle['open'] else '#F23645'
            self.ax.axhline(float(live_data["price"]), color=line_color, linestyle='--', linewidth=1, zorder=1)

        self.chart_widget.draw()

if __name__ == "__main__":
    TudaMobileApp().run()
