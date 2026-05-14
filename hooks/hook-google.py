from PyInstaller.utils.hooks import collect_all
datas, binaries, hiddenimports = collect_all('google.auth')
d2, b2, h2 = collect_all('google.oauth2')
datas += d2; binaries += b2; hiddenimports += h2
d3, b3, h3 = collect_all('googleapiclient')
datas += d3; binaries += b3; hiddenimports += h3
