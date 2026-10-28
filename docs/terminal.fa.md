# رابط Textual و شخصی‌سازی ترمینال

از پوشهٔ پروژه اجرا کنید:

```sh
uv run devforge
```

روش بدون uv:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m devforge
```

این نصب فقط وابستگی‌های خود DevForge را در محیط مجازی آماده می‌کند؛ Zsh،
افزونه‌های شل و Starship را روی حساب کاربر فعال نمی‌کند. در توزیع‌هایی که
venv جزو بستهٔ اصلی Python نیست، پشتیبانی venv را با مدیر بستهٔ توزیع نصب کنید؛
مثلاً Debian/Ubuntu بستهٔ `python3-venv` دارد.

## رابط برنامه

رابط پیش‌فرض اکنون Textual است: دسته‌ها در ستون کناری، ابزار و عملیات در پنل
اصلی، و گزارش اجرا در پایین. با ماوس یا جهت‌ها، Tab و Enter حرکت کنید؛ Escape
بازگشت، Ctrl+R تازه‌سازی و q خروج است. هنگام اجرای عملیات، ابتدا آن را تمام
یا پنجرهٔ ورودی را لغو کنید؛ برنامه عملیات مدیر بسته را در میانه رها نمی‌کند.

تم پیش‌فرض Tokyo Night است. از انتخاب‌گر پایین ستون کناری می‌توانید Catppuccin،
Nord، Dracula یا حالت روشن را برای همان اجرای برنامه انتخاب کنید. این تمِ
رابط DevForge است؛ تم شل کاربر تنظیم جداگانه‌ای دارد. انتخاب تم TUI در این نسخه
بین اجراها ذخیره نمی‌شود.

قبل از تغییر، پنجرهٔ قابل اسکرول طرح اجرا باز می‌شود و دکمهٔ Cancel فوکوس
دارد؛ Enter به‌تنهایی تغییر را تأیید نمی‌کند. فرمان‌های sudo و chsh پس از تأیید
از طریق ترمینال واقعی اجرا می‌شوند تا رمز حساب داخل فرم‌ها، تنظیمات یا لاگ
DevForge قرار نگیرد. بعد از فرمان، رابط برمی‌گردد.

برای SSH ساده یا نصب بدون وابستگی Textual:

```sh
python3 -m devforge tui --plain
```

در نبود Textual یا روی `TERM=dumb`، منوی شماره‌ای جایگزین باز می‌شود. `NO_COLOR`
و `--no-color` رعایت می‌شوند. Textual به X11، Wayland یا دسکتاپ نیاز ندارد.
نصب‌کنندهٔ انتشار، Textual را در `share/devforge/runtime` نصب می‌کند؛ Python
سیستمی با pip تغییر نمی‌کند. با `DEVFORGE_INSTALL_TUI=0` می‌توانید این مرحله
را حذف کنید و CLI و منوی ساده را نگه دارید. اگر ساخت محیط مجازی یا اتصال PyPI
ناموفق باشد، پیام اصلاح مشکل نمایش داده می‌شود و CLI قابل استفاده می‌ماند.

## Terminal studio

در ستون کناری **Terminal studio** را انتخاب کنید؛ از منوی ابزارهای Zsh و
Starship هم به همین بخش می‌رسید. هر مؤلفه انتخابی مستقل است:

1. **Install Zsh only** فقط بستهٔ Zsh را نصب می‌کند.
2. **Enable history suggestions** فقط افزونهٔ پیشنهاد از history محلی را
   دریافت و فعال می‌کند. خواندن یا ارسال history توسط DevForge انجام نمی‌شود.
3. **Enable syntax highlighting** فقط رنگ‌بندی نحوی فرمان‌های Zsh را فعال می‌کند.
4. یکی از تم‌های خود Zsh: Minimal، Midnight یا Classic.
5. **Install Starship only** فقط باینری Starship را نصب می‌کند؛ انتخاب تم جداست.
6. یکی از تم‌های Starship: Minimal، Midnight یا Server.
7. تغییر شل پیش‌فرض فقط با **Change my default login shell to Zsh** انجام می‌شود.

هیچ گزینهٔ «نصب همه» یا انتخاب نصب از پیش فعال‌شده وجود ندارد. اگر افزونه یا تم
را پیش از پیش‌نیازش انتخاب کنید، برنامه نام پیش‌نیاز را اعلام می‌کند؛ آن را
پنهانی نصب نمی‌کند. پیش‌نمایش تم با حرکت روی گزینه‌های تم نمایش داده می‌شود.
تم‌های فعلی از نویسه‌های معمول استفاده می‌کنند و Nerd Font لازم ندارند.

برای استفاده بدون تغییر شل پیش‌فرض، پس از نصب و انتخاب تنظیمات یک `zsh` جدید
باز کنید. تغییر شل پیش‌فرض تنها حساب جاری را هدف می‌گیرد و مسیر انتخابی باید
در `/etc/shells` ثبت شده باشد. اگر chsh روی توزیع وجود نداشته باشد، پیام روشن
برای استفاده از ابزار مدیریت حساب همان توزیع نمایش داده می‌شود.

## معادل‌های خط فرمان

```sh
uv run devforge terminal show
uv run devforge --dry-run terminal install-zsh
uv run devforge terminal install-zsh
uv run devforge terminal autosuggestions
uv run devforge terminal highlighting
uv run devforge terminal zsh-theme --theme midnight
uv run devforge terminal install-starship
uv run devforge terminal starship-theme --theme server
uv run devforge terminal disable-autosuggestions
uv run devforge terminal disable-highlighting
uv run devforge terminal reset-prompt
uv run devforge terminal remove-autosuggestions
uv run devforge terminal remove-highlighting
uv run devforge terminal remove
uv run devforge terminal default-shell
```

Disable، بارگذاری افزونه را متوقف می‌کند و فایل دانلودشده را نگه می‌دارد.
Remove مربوط به افزونه، فایل‌های همان افزونه را هم از پوشهٔ DevForge پاک می‌کند.
`terminal remove` فقط بلوک تنظیمات مدیریت‌شده را حذف می‌کند؛ بستهٔ Zsh، باینری
Starship و فایل‌های دیگر کاربر را پاک نمی‌کند. حذف بسته‌ها از منوی همان ابزار
انجام می‌شود. حذف Starship، انتخاب prompt مدیریت‌شدهٔ آن را هم بازنشانی می‌کند.
حذف Zsh در حالی که شل ورود حساب است مسدود می‌شود.

## فایل‌ها و حفظ تنظیمات

- بلوک `devforge terminal` در `.zshrc` افزوده یا جایگزین می‌شود؛ محتوای بیرون
  بلوک باقی می‌ماند و قبل از اولین ویرایش پشتیبان `.devforge.bak` ساخته می‌شود.
- `ZDOTDIR` درون خانهٔ کاربر پشتیبانی می‌شود. مسیر بیرون خانه، فایل symlink و
  نشانگرهای خراب بلوک، به‌جای بازنویسی مبهم، پیام خطای قابل‌فهم می‌دهند.
- تنظیمات انتخاب‌ها: `~/.config/devforge/terminal.json`.
- تنظیمات تم Starship: `~/.config/devforge/starship.toml`؛ فایل شخصی
  `~/.config/starship.toml` بازنویسی نمی‌شود.
- افزونه‌ها: `~/.local/share/devforge/terminal/plugins/`، با نسخه و SHA256 ثابت.
  syntax-highlighting پس از prompt و دیگر افزونه‌ها بارگذاری می‌شود.
- افزونه‌های تکراریِ بارگذاری‌شده با بررسی تابع مربوط دوباره source نمی‌شوند.
  چارچوب‌هایی مثل Oh My Zsh حذف نمی‌شوند؛ prompt انتخابی DevForge در پایان
  بارگذاری `.zshrc` روی prompt قبلی اعمال می‌شود.

در اجرای `sudo devforge`، تنظیمات یک کاربر دیگر حدس زده نمی‌شود؛ برای تنظیم
ترمینال حساب خود، DevForge را بدون sudo اجرا کنید. مراحل نصب بسته در صورت نیاز
جداگانه sudo می‌گیرند.

## سازگاری و بررسی فایل مرجع

نصب بستهٔ Zsh برای Debian/Ubuntu، Fedora/RHEL و مشتق‌ها، Arch/Manjaro، openSUSE
و Alpine با مدیر بستهٔ همان خانواده برنامه‌ریزی می‌شود. افزونه‌ها از آرشیو
رسمی پروژه با checksum ثابت نصب می‌شوند و وابسته به نام بستهٔ افزونه در مخازن
توزیع نیستند. Starship از باینری رسمی musl برای x86_64، aarch64 و i686 استفاده
می‌کند. خانواده یا معماری فاقد نگاشت، با پیام مشخص متوقف می‌شود؛ ادعای آزمون
نصب واقعی روی تمام توزیع‌های لینوکس وجود ندارد.

در فایل مرجع `/run/media/mrhr/Ventoy/setup-zsh.sh` ایدهٔ پشتیبان‌گیری و نام دو
افزونه مفید بود. این موارد منتقل نشدند: اجرای نصب‌کنندهٔ دانلودشده با `sh`،
حدس‌زدن اولین کاربر با UID بالا، chown بازگشتی، نادیده‌گرفتن خطاهای clone با
`|| true`، بازنویسی شکنندهٔ plugins با Perl و تغییر خودکار شل ورود. فایل مرجع
اجرا یا تغییر داده نشده است؛ نصب Oh My Zsh هم برای این قابلیت‌ها ضروری نیست.
