# LUX

واحد مدیریت درس‌ها و تحصیل شخصی — اپ اندروید (Flutter).

## ساخت APK (از طریق GitHub Actions)

1. یک مخزن (repo) روی GitHub بساز و کل محتویات این پوشه را در شاخه‌ی `main` آپلود کن
   (پوشه‌ی `.github` هم باید باشد).
2. بخش **Actions → Build LUX APK → Run workflow** را بزن (با هر push هم خودکار اجرا می‌شود).
3. بعد از پایان، از قسمت **Artifacts** فایل `lux-apk` را دانلود کن؛ داخلش `lux.apk` است.

## کلید امضا (برای اینکه آپدیت‌ها روی نصب قبلی بنشینند)

یک‌بار روی کامپیوتر:

```
keytool -genkeypair -v -keystore lux.jks -alias lux -keyalg RSA -keysize 2048 -validity 10000
base64 -w0 lux.jks
```

سپس در GitHub: **Settings → Secrets and variables → Actions** چهار Secret بساز:

| نام | مقدار |
|---|---|
| `KEYSTORE_BASE64` | خروجی دستور base64 |
| `KEYSTORE_PASSWORD` | رمز keystore |
| `KEY_ALIAS` | `lux` |
| `KEY_PASSWORD` | رمز کلید |

فایل `lux.jks` را در چند جای امن نگه دار؛ اگر گم شود، دیگر نمی‌شود آپدیت داد.

## ساختار

- `lib/core` پالت، تم، ابزار تاریخ شمسی
- `lib/data` پایگاه‌داده‌ی SQLite (طرح کامل همه‌ی ماژول‌ها)
- `lib/engine` موتور محاسبات (معدل، نمره‌ی لازم، برنامه‌ریز، SM-2، آمار)
- `lib/ui/charts` نمودارهای اختصاصی
- `lib/ui/onboarding` اولین اجرا
- `tool/` اسکریپت‌های ساخت (CI)
