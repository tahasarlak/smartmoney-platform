# TRADF – بسته اتصال MT5 Demo برای فارکس و طلا

این بسته برای نسخه آپلودشده پروژه ساخته شده و یک **پل داده فقط‌خواندنی** بین ترمینال MetaTrader 5 روی Windows و Backend فعلی TRADF اضافه می‌کند.

## نمادها
- EURUSD
- GBPUSD
- USDJPY
- USDCHF
- AUDUSD
- USDCAD
- NZDUSD
- XAUUSD

تایم‌فریم‌ها: 1m، 5m، 15m، 1h، 4h.

## معماری و محدودیت ایمنی
- ترمینال MT5 روی Windows اجرا می‌شود؛ کتابخانه رسمی MetaTrader5 به ترمینال محلی متصل می‌شود.
- Bridge فقط داده OHLCV را از ترمینال می‌خواند و با HTTPS به Backend ارسال می‌کند.
- Bridge فقط حساب DEMO را قبول می‌کند و در صورت تشخیص حساب REAL متوقف می‌شود.
- هیچ فراخوانی `order_send` وجود ندارد؛ این نسخه سفارش ثبت، تغییر یا لغو نمی‌کند.
- Backend برای دریافت داده به `TRADF_MT5_BRIDGE_TOKEN` نیاز دارد و در صورت نبود secret، مسیر دریافت را fail-closed می‌کند.
- API key، رمز عبور، شماره حساب و توکن در دیتابیس یا heartbeat ذخیره نمی‌شوند.
- نمادهای با پسوند بروکر از طریق `MT5_SYMBOL_MAP` قابل تنظیم‌اند.

## نصب در پروژه
1. ZIP را Extract کن.
2. PowerShell را باز کن.
3. Installer را با مسیر پروژه اجرا کن:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\INSTALL_MT5_FOREX.ps1 -ProjectRoot "Q:\programing\website\New-bot\smartmoney-platform"
```

Installer از فایل‌های جایگزین‌شونده بکاپ می‌گیرد. هیچ Migration، Deploy، Commit یا Push را اجرا نمی‌کند.

## Secret در Render
یک توکن تصادفی بساز:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

مقدار را فقط در Render به‌عنوان Environment Variable با نام `TRADF_MT5_BRIDGE_TOKEN` ثبت کن. مقدار آن را در گفتگو یا Git commit نکن.

## اجرای Migration
پس از بررسی زنجیره Migration، در GitHub Actions یا محیط کنترل‌شده اجرا کن:

```powershell
Set-Location "Q:\programing\website\New-bot\smartmoney-platform\backend"
$env:DIRECT_URL = "YOUR_DIRECT_DATABASE_URL"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

Migration جدید `0006_mt5_market_data` پس از `0005_tradf_worker_heartbeat` قرار دارد. قبل از اجرا از Neon backup/restore point بگیر. `DIRECT_URL` را در فایل یا خروجی ترمینال چاپ نکن.

## نصب Windows Bridge
1. MetaTrader 5 را نصب و با حساب Demo بروکر وارد کن.
2. مطمئن شو ترمینال به سرور Demo وصل است.
3. Python 3.12 نسخه 64-bit نصب کن.
4. در پوشه `mt5-bridge` فایل `.env.example` را به `.env` کپی کن.
5. `TRADF_API_BASE_URL` را با آدرس Render خودت و `TRADF_MT5_BRIDGE_TOKEN` را با همان secret ثبت‌شده در Render پر کن.
6. اگر بروکر نمادها را با پسوند ارائه می‌کند، `MT5_SYMBOL_MAP` را تنظیم کن؛ مثلاً:
   `{"EURUSD":"EURUSD.a","XAUUSD":"GOLD"}`
7. اجرا:

```powershell
Set-Location .\mt5-bridge
.\run_bridge.ps1
```

`MT5_HISTORY_BARS` پیش‌فرض 7000 است. برای بک‌تست 21 روزه در M5 تقریباً 6048 کندل لازم است؛ داده موجود در ترمینال و محدودیت Max bars in chart باید کافی باشد. برای M1 تاریخچه 7000 کندل فقط حدود 4.8 روز را پوشش می‌دهد؛ پس قبل از بک‌تست M1 باید تاریخچه بیشتری بارگیری شود.

## API
- `GET /api/v1/mt5/market/status`
- `GET /api/v1/mt5/market/symbols`
- `GET /api/v1/mt5/market/klines?symbol=EURUSD&timeframe=15m&limit=300`
- `POST /api/v1/mt5/analysis/multi-timeframe`
- `POST /api/v1/mt5/bridge/heartbeat` (نیازمند X-TRADF-BRIDGE-TOKEN)
- `POST /api/v1/mt5/bridge/candles` (نیازمند X-TRADF-BRIDGE-TOKEN)

صفحه UI: `/forex`

## تست‌ها
در backend:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_mt5_market_data.py -q
```

سپس کل تست‌های غیر DB و build فرانت‌اند را اجرا کن.

## نکته درباره بک‌تست
این بسته داده MT5 را ذخیره و در اختیار تحلیل قرار می‌دهد؛ بک‌تست MT5 با مدل دقیق contract size، tick value، margin، commissions، swap، spread و slippage بروکر هنوز نیازمند مشخصات بروکر و اعتبارسنجی جداگانه است. داده کندلی به‌تنهایی برای اثبات قابلیت اجرای زنده یا سودآوری کافی نیست.
