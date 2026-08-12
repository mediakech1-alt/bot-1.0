[app]

# (str) Title of your application
title = TUDA AI cTrader

# (str) Package name
package.name = tudaai

# (str) Package domain (needed for android packaging)
package.domain = org.tuda

# (str) Source files where the app lives
source.dir = .

# (list) Source files to include (let empty to include all the files)
source.exts = py,png,jpg,kv,atlas

# (str) Application versioning
version = 1.0

# (list) Application requirements
# حيدنا android ودرنا kivy==master باش نتفاداو المشكل ديال Version not found
requirements = python3,kivy==master,certifi,six

# (str) Supported orientations
orientation = portrait

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

# (list) Permissions
android.permissions = INTERNET

# (list) The Android archs to build for
# زدنا هادي باش يبني غير للهواتف الجداد ويزرب فالبناء
android.archs = arm64-v8a

# (bool) automatically accept SDK license
android.accept_sdk_license = True

# (int) Target Android API, should be as high as possible.
android.api = 33

# (int) Minimum API your APK will support.
android.min_api = 21

# (str) Android SDK version to use
# حيدناها باش ما تعطيش Warning بالأحمر
# android.sdk = 33

# (str) Android NDK version to use
# حيدناها باش Buildozer ياخد النسخة المتوافقة لراسو
# android.ndk = 25b
