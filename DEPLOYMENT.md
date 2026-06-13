# استقرار داشبورد روی VPS

این راهنما برای Ubuntu 22.04 یا 24.04، Docker Compose، Nginx نصب‌شده روی خود VPS و دامنه `pizo.werifum.ir` نوشته شده است.

## معماری

- کانتینر FastAPI فقط روی `127.0.0.1:8228` در دسترس است.
- Nginx درخواست‌های دامنه را به این پورت reverse proxy می‌کند.
- فایل‌های `Data/` به‌صورت volume فقط‌خواندنی mount می‌شوند.
- برنامه با یک worker اجرا می‌شود؛ هر worker داده‌ها را جداگانه در RAM بارگذاری می‌کند.
- برای این حجم داده، VPS با حداقل ۱ گیگابایت RAM و ترجیحاً ۲ گیگابایت RAM پیشنهاد می‌شود.

## ۱. تنظیم DNS

در پنل DNS دامنه، رکورد زیر را بسازید:

```text
Type: A
Name: pizo
Value: VPS_PUBLIC_IP
TTL: Auto
```

اگر IPv6 روی VPS تنظیم نشده، رکورد `AAAA` نسازید. انتشار DNS را بررسی کنید:

```bash
dig +short pizo.werifum.ir
```

## ۲. نصب Docker، Nginx و Certbot

ابتدا وارد VPS شوید:

```bash
ssh root@VPS_PUBLIC_IP
```

بسته‌های پایه را نصب کنید:

```bash
sudo apt update
sudo apt install -y ca-certificates curl nginx snapd
```

Docker را از repository رسمی نصب کنید:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker nginx
```

Certbot را از Snap نصب کنید:

```bash
sudo snap install core
sudo snap refresh core
sudo snap install --classic certbot
sudo ln -sfn /snap/bin/certbot /usr/local/bin/certbot
```

نسخه‌ها را کنترل کنید:

```bash
docker --version
docker compose version
nginx -v
```

## ۳. انتقال پروژه

روی سیستم شخصی، از پوشه پروژه اجرا کنید:

```bash
rsync -az \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '.venv-win' \
  --exclude 'node_modules' \
  ./ root@VPS_PUBLIC_IP:/opt/pizo-dashboard/
```

سپس روی VPS:

```bash
cd /opt/pizo-dashboard
cp .env.example .env
```

پورت پیش‌فرض `8228` است. اگر این پورت روی VPS اشغال است، مقدار `APP_PORT` را در `.env` تغییر دهید و همان مقدار را در فایل Nginx نیز جایگزین کنید.

## ۴. ساخت و اجرای کانتینر

```bash
cd /opt/pizo-dashboard
sudo docker compose up -d --build
sudo docker compose ps
```

اولین build به اینترنت و چند دقیقه زمان نیاز دارد. سلامت برنامه را بررسی کنید:

```bash
curl http://127.0.0.1:8228/health
```

خروجی صحیح:

```json
{"status":"ok"}
```

مشاهده لاگ‌ها:

```bash
sudo docker compose logs -f --tail=200 app
```

## ۵. تنظیم Nginx

```bash
sudo cp deploy/nginx/pizo.werifum.ir.conf \
  /etc/nginx/sites-available/pizo.werifum.ir
sudo ln -sfn /etc/nginx/sites-available/pizo.werifum.ir \
  /etc/nginx/sites-enabled/pizo.werifum.ir
sudo nginx -t
sudo systemctl reload nginx
```

سپس بررسی کنید:

```bash
curl -I http://pizo.werifum.ir
```

در صورت استفاده از UFW:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

پورت `8228` را در firewall عمومی باز نکنید؛ Docker آن را فقط روی loopback منتشر می‌کند.

## ۶. فعال‌سازی HTTPS

پس از اینکه نسخه HTTP دامنه باز شد:

```bash
sudo certbot --nginx -d pizo.werifum.ir
```

در مراحل Certbot، انتقال خودکار HTTP به HTTPS را انتخاب کنید. سپس:

```bash
sudo nginx -t
sudo systemctl reload nginx
sudo certbot renew --dry-run
systemctl status certbot.timer
```

نشانی نهایی:

```text
https://pizo.werifum.ir
```

## به‌روزرسانی برنامه

فایل‌های جدید پروژه را دوباره با `rsync` منتقل کنید و روی VPS اجرا کنید:

```bash
cd /opt/pizo-dashboard
sudo docker compose up -d --build --remove-orphans
sudo docker image prune -f
```

## به‌روزرسانی فقط داده‌ها

فایل‌های جدید را با همان نام و header داخل `/opt/pizo-dashboard/Data/` جایگزین کنید. چون داده‌ها هنگام startup در حافظه cache می‌شوند، سپس اجرا کنید:

```bash
cd /opt/pizo-dashboard
sudo docker compose restart app
sudo docker compose ps
```

برای تغییر داده‌ها نیازی به build مجدد image نیست.

## عیب‌یابی

وضعیت و لاگ کانتینر:

```bash
sudo docker compose ps
sudo docker compose logs --tail=300 app
```

لاگ Nginx:

```bash
sudo tail -f /var/log/nginx/error.log
sudo tail -f /var/log/nginx/access.log
```

کنترل پورت محلی:

```bash
sudo ss -lntp | grep ':8228'
curl -v http://127.0.0.1:8228/health
```

کنترل Nginx:

```bash
sudo nginx -t
curl -I -H 'Host: pizo.werifum.ir' http://127.0.0.1
```

توقف و اجرای مجدد:

```bash
sudo docker compose down
sudo docker compose up -d
```
