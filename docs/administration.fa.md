# مدیریت سرویس‌ها و بک‌آپ در DevForge 1.4

این تغییرات برای نسخهٔ محلی 1.4.0 آماده شده‌اند؛ انتشار در GitHub انجام نشده است.
از همین checkout با `python3 -m devforge` اجرا کنید. نصب‌کنندهٔ این شاخه پس از
انتشار آرشیو 1.4.0 و SHA256SUMS قابل استفاده از اینترنت خواهد بود.

## منوها

برنامه بدون آرگومان، در ترمینال منوی دسته‌ها را باز می‌کند:

- زبان‌ها و ابزارهای بسته
- دیتابیس‌ها: MySQL، MariaDB، PostgreSQL، Redis، MongoDB
- سرویس‌های وب و سیستم، شامل Nginx
- مجازی‌سازی: KVM و `kvm-gui`، همان virt-manager
- زیر هر ابزار: نصب، به‌روزرسانی، نسخه‌های نصب‌شده، حذف و عملیات مرتبط
- زیر هر دیتابیس: ساخت و فهرست بک‌آپ‌های همان دیتابیس
- زیر سرویس‌ها: وضعیت، start/stop/restart/reload/enable/disable
- زیر Nginx: نمایش تنظیمات، بررسی صحت، اعمال فایل ویرایش‌شده

رابط اصلی اکنون Textual است و به دسکتاپ یا GUI نیاز ندارد. منوی شماره‌ای
با `devforge tui --plain` همچنان برای ترمینال ساده و SSH در دسترس است.
راهنمای رابط جدید و شخصی‌سازی شل در [terminal.fa.md](terminal.fa.md) آمده است. `NO_COLOR=1` یا `--no-color tui`
رنگ‌ها را غیرفعال می‌کند. تغییرات به تأیید صریح `y` نیاز دارند؛ Enter و قطع
ورودی تأیید محسوب نمی‌شوند. `--yes` انتخاب آگاهانه برای اجرای بدون پرسش است.

## بک‌آپ

```sh
python3 -m devforge --dry-run backup mysql
python3 -m devforge backup mysql app
python3 -m devforge backup mariadb
python3 -m devforge backup postgresql app
python3 -m devforge backup mongodb
python3 -m devforge backup mongodb app --client-config ~/.config/mongodb/dump.yml
python3 -m devforge backup redis
```

ابزارهای لازم: `mysqldump`، `mariadb-dump`، `pg_dump`، `mongodump`، `redis-cli`.
نصب سرور به معنی نصب بودن تمام این کلاینت‌ها نیست. در نبود کلاینت، برنامه
پیش از ساخت فایل، علت و نام ابزار لازم را اعلام می‌کند.

رمز را در آرگومان فرمان ننویسید. MySQL/MariaDB از فایل خصوصی تنظیمات کلاینت
و احراز هویت سوکت، PostgreSQL از `.pgpass` یا احراز هویت محلی، Redis از
روش‌های بومی از جمله `REDISCLI_AUTH` استفاده می‌کنند. برای MongoDB احرازهویت‌دار
از فایل YAML پشتیبانی‌شده توسط `mongodump --config` با مجوز `600` استفاده کنید؛
این فایل می‌تواند URI و رمز را نگه دارد و محتویاتش در plan چاپ نمی‌شود.
این نسخه فرم اتصال عمومی به سرور راه دور ندارد.

خروجی‌ها در `$XDG_STATE_HOME/devforge/backups/<database-engine>/` هستند؛
پیش‌فرض `~/.local/state/devforge/backups/`. پوشهٔ هر دیتابیس `700` و فایل‌ها
`600` هستند. بک‌آپ‌ها رمزنگاری نمی‌شوند. فایل ابتدا با نام موقت خصوصی ساخته
می‌شود؛ فقط پس از موفقیت، نام نهایی منتشر می‌شود و فایل موجود بازنویسی نمی‌شود.
شکست یا خروجی خالی، بک‌آپ نهایی ایجاد نمی‌کند. خروجی حجیم در حافظه جمع نمی‌شود.

- MySQL/MariaDB: SQL همراه routines/events/triggers و snapshot تراکنشی.
  برای جداول غیرتراکنشی یا تغییر ساختار هم‌زمان، برنامهٔ توقف نوشتن لازم است.
- PostgreSQL: آرشیو custom برای یک دیتابیس؛ نام دیتابیس اجباری است.
  نقش‌ها و tablespaceهای کلاستر جزو `pg_dump` نیستند و به بک‌آپ جداگانه نیاز دارند.
- MongoDB: آرشیو gzip؛ سازگاری snapshot هنگام نوشتن هم‌زمان یا replica set
  به رویهٔ متناسب با استقرار، از جمله oplog، نیاز دارد.
- Redis: فایل RDB از کل instance، شامل همهٔ logical databaseها؛ دسترسی replication لازم است.

بازیابی خودکار، زمان‌بندی، retention، رمزنگاری، انتقال خارج از سرور و PITR در
این نسخه پیاده‌سازی نشده‌اند. برای آزمون بازیابی از کلاینت بومی و یک دیتابیس
ایزوله استفاده کنید؛ بازیابی روی دیتابیس زنده از منوی عمومی عرضه نشده است.

## Nginx

```sh
python3 -m devforge status nginx
python3 -m devforge --dry-run uninstall nginx
python3 -m devforge uninstall nginx
python3 -m devforge config nginx show
python3 -m devforge --dry-run config nginx apply /path/to/edited-nginx.conf
python3 -m devforge config nginx apply /path/to/edited-nginx.conf
python3 -m devforge service nginx reload
```

حذف پیش‌فرض تنظیمات را نگه می‌دارد؛ purge انتخاب جداگانه است. بسته‌های واقعاً
نصب‌شده بررسی می‌شوند و روی apt نتیجهٔ simulation پیش از تأیید نمایش داده
می‌شود. حذف وابستگی‌های حساس مسدود می‌شود. نصب دستی خارج از مدیر بسته، به
حذف‌کنندهٔ اصلی همان نصب نیاز دارد.

برای تغییر `nginx.conf` ابتدا نسخهٔ ویرایش‌شده را در فایل جدا آماده کنید.
برنامه با `nginx -t -c` فایل پیشنهادی را بررسی می‌کند، فایل قبلی را نگه می‌دارد،
فایل جدید را می‌نویسد و دوباره در مسیر نصب بررسی می‌کند. اگر بررسی دوم شکست
بخورد، محتوای بلافاصله پیش از تغییر بازگردانده می‌شود. reload مرحله‌ای صریح و
جداگانه در منوی همان Nginx است. این جریان فقط `nginx.conf` را مدیریت می‌کند؛
ویرایش عمومی تنظیمات تمام سرویس‌ها یا فایل‌های include هنوز پشتیبانی نمی‌شود.
فقط فایل تنظیمات مورد اعتماد خودتان را برای بررسی با دسترسی root انتخاب کنید.

## KVM و دسکتاپ

```sh
python3 -m devforge --dry-run install kvm
python3 -m devforge install kvm
python3 -m devforge service kvm status
python3 -m devforge service kvm start
python3 -m devforge install kvm-gui
python3 -m devforge doctor --offline
```

`kvm` بسته‌های QEMU و libvirt را مدیریت می‌کند. `kvm-gui`، virt-manager است؛
روی سرور بدون محیط دسکتاپ عرضه نمی‌شود. کلاینت دسکتاپ می‌تواند از طریق SSH
به libvirt سرور وصل شود. ساخت، حذف، snapshot و مدیریت دیسک ماشین‌های مجازی
جزو این نسخه نیست. دسترسی `/dev/kvm` و فعال بودن virtualization لازم است؛
برنامه گروه کاربر، شبکهٔ libvirt یا دیسک VMها را خودکار تغییر نمی‌دهد.
کنترل سرویس KVM فعلاً از `libvirtd` استفاده می‌کند؛ میزبان‌های دارای daemonهای
ماژولار مثل `virtqemud` باید socketهای مربوط را با ابزار توزیع مدیریت کنند.

## گزینه‌های ظاهر TUI

- [Textual و گالری نمونه‌ها](https://textual.textualize.io/): انتخاب پیشنهادی
  برای نسخهٔ تمام‌صفحهٔ Python با جدول، جست‌وجو، تب و کنترل با صفحه‌کلید.
- [Rich](https://rich.readthedocs.io/en/stable/): برای جدول، پنل و progress زیبا
  در جریان خطی فعلی؛ به‌تنهایی چارچوب کامل منو نیست.
- [prompt_toolkit](https://python-prompt-toolkit.readthedocs.io/en/master/):
  برای منو و فرم تعاملی، تکمیل خودکار و برنامه‌های تمام‌صفحه.

رابط اصلی به Textual منتقل شده است؛ تم رابط و تم Zsh/Starship انتخاب‌های
جداگانه‌اند. راهنمای [شخصی‌سازی ترمینال](terminal.fa.md) را ببینید.
