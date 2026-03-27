## Deployment Guide for JAIP

This guide covers deploying JAIP to a production environment on Linux.

## Prerequisites

- Linux server (Ubuntu 20.04+ recommended)
- Python 3.12+
- Nginx
- Domain name with DNS configured
- ORCID Production Credentials

## Step 1: Production Environment Setup

### 1.1 Update Production .env

```bash
# Application
APP_NAME="JAIP - Journal for AI Generated Papers"
DEBUG=False
SECRET_KEY=<generated-with-openssl-rand-hex-32>
BASE_URL=https://jaip.yourdomain.com

# Database (consider PostgreSQL for production)
DATABASE_URL=sqlite:///./data/jaip.db

# ORCID OAuth (Production credentials)
ORCID_CLIENT_ID=<production-client-id>
ORCID_CLIENT_SECRET=<production-client-secret>
ORCID_REDIRECT_URI=https://jaip.yourdomain.com/auth/callback
ORCID_AUTH_URL=https://orcid.org/oauth/authorize
ORCID_TOKEN_URL=https://orcid.org/oauth/token
ORCID_API_URL=https://pub.orcid.org/v3.0

# OpenAlex
OPENALEX_API_EMAIL=admin@yourdomain.com

# File Storage
DATA_DIR=/var/www/ai_journal/data
MAX_FILE_SIZE_MB=50

# Server
PORT=8002
WORKERS=3
HOST=127.0.0.1

# Session
SESSION_MAX_AGE=86400
```

### 1.2 Generate Secret Key

```bash
openssl rand -hex 32
```

## Step 2: Systemd Service

### 2.1 Create Service File

Create `/etc/systemd/system/jaip.service`:

```ini
[Unit]
Description=JAIP - Journal for AI Generated Papers
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/ai_journal
Environment="PATH=/var/www/ai_journal/venv/bin"
ExecStart=/var/www/ai_journal/venv/bin/uvicorn main:app --workers 3 --host 127.0.0.1 --port 8002

# Restart policy
Restart=always
RestartSec=10

# Security
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/www/ai_journal/data
ReadOnlyPaths=/var/www/ai_journal

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=jaip

[Install]
WantedBy=multi-user.target
```

### 2.2 Set Permissions

```bash
# Set ownership
sudo chown -R www-data:www-data /var/www/ai_journal

# Set permissions
sudo chmod -R 755 /var/www/ai_journal
sudo chmod -R 755 /var/www/ai_journal/data

# Make sure data directory is writable
sudo chmod -R 775 /var/www/ai_journal/data
```

### 2.3 Enable and Start Service

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable jaip

# Start service
sudo systemctl start jaip

# Check status
sudo systemctl status jaip

# View logs
sudo journalctl -u jaip -f
```

## Step 3: Nginx Configuration

### 3.1 Create Nginx Config

Create `/etc/nginx/sites-available/jaip`:

```nginx
# HTTP server - redirect to HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name jaip.yourdomain.com;

    # Redirect to HTTPS
    return 301 https://$server_name$request_uri;
}

# HTTPS server
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name jaip.yourdomain.com;

    # SSL certificates (will be configured by certbot)
    ssl_certificate /etc/letsencrypt/live/jaip.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/jaip.yourdomain.com/privkey.pem;
    ssl_trusted_certificate /etc/letsencrypt/live/jaip.yourdomain.com/chain.pem;

    # SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # Max upload size
    client_max_body_size 50M;

    # Proxy to FastAPI application
    location / {
        proxy_pass http://127.0.0.1:8002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # HTMX support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Timeouts for file uploads
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    # Static files - direct serving for better performance
    location /static/ {
        alias /var/www/ai_journal/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Access and error logs
    access_log /var/log/nginx/jaip_access.log;
    error_log /var/log/nginx/jaip_error.log;
}
```

### 3.2 Enable Site

```bash
# Create symlink
sudo ln -s /etc/nginx/sites-available/jaip /etc/nginx/sites-enabled/

# Test configuration
sudo nginx -t

# If test passes, reload nginx
sudo systemctl reload nginx
```

## Step 4: SSL Certificate

### 4.1 Install Certbot

```bash
sudo apt update
sudo apt install certbot python3-certbot-nginx
```

### 4.2 Obtain Certificate

```bash
# Get certificate and auto-configure nginx
sudo certbot --nginx -d jaip.yourdomain.com

# Follow prompts to:
# - Enter email address
# - Agree to Terms of Service
# - Choose whether to redirect HTTP to HTTPS (recommended: yes)
```

### 4.3 Auto-Renewal

Certbot automatically sets up renewal. Test it:

```bash
sudo certbot renew --dry-run
```

## Step 5: Firewall Configuration

```bash
# Allow HTTP and HTTPS
sudo ufw allow 'Nginx Full'

# Check status
sudo ufw status
```

## Step 6: Monitoring and Logging

### 6.1 View Application Logs

```bash
# Real-time logs
sudo journalctl -u jaip -f

# Last 100 lines
sudo journalctl -u jaip -n 100

# Logs since boot
sudo journalctl -u jaip -b
```

### 6.2 View Nginx Logs

```bash
# Access log
sudo tail -f /var/log/nginx/jaip_access.log

# Error log
sudo tail -f /var/log/nginx/jaip_error.log
```

### 6.3 Monitor System Resources

```bash
# Check service status
sudo systemctl status jaip

# Check if port is listening
sudo netstat -tlnp | grep 8002

# Check disk usage
df -h
```

## Step 7: Backup Strategy

### 7.1 Database Backup

```bash
# Create backup script
sudo nano /usr/local/bin/backup-jaip.sh
```

```bash
#!/bin/bash
BACKUP_DIR="/var/backups/jaip"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# Backup database
cp /var/www/ai_journal/data/jaip.db $BACKUP_DIR/jaip_$DATE.db

# Backup papers directory
tar -czf $BACKUP_DIR/papers_$DATE.tar.gz /var/www/ai_journal/data/papers

# Keep only last 7 days of backups
find $BACKUP_DIR -name "jaip_*.db" -mtime +7 -delete
find $BACKUP_DIR -name "papers_*.tar.gz" -mtime +7 -delete

echo "Backup completed: $DATE"
```

```bash
# Make executable
sudo chmod +x /usr/local/bin/backup-jaip.sh

# Set up daily cron job
sudo crontab -e
```

Add line:
```
0 2 * * * /usr/local/bin/backup-jaip.sh >> /var/log/jaip-backup.log 2>&1
```

## Step 8: Maintenance

### 8.1 Update Application

```bash
cd /var/www/ai_journal

# Pull latest changes (if using git)
git pull

# Activate virtual environment
source venv/bin/activate

# Update dependencies if needed
pip install -r requirements.txt

# Restart service
sudo systemctl restart jaip
```

### 8.2 Database Migration

If database schema changes:

```bash
# Backup first!
cp data/jaip.db data/jaip_backup.db

# Run migrations
python -c "from models.database import init_db; init_db()"

# Restart service
sudo systemctl restart jaip
```

## Step 9: Performance Tuning

### 9.1 Increase Workers (if needed)

Edit `/etc/systemd/system/jaip.service`:

```ini
ExecStart=/var/www/ai_journal/venv/bin/uvicorn main:app --workers 5 --host 127.0.0.1 --port 8002
```

Reload and restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart jaip
```

### 9.2 Database Optimization

For high traffic, consider migrating to PostgreSQL:

1. Install PostgreSQL
2. Create database and user
3. Update DATABASE_URL in .env
4. Install psycopg2: `pip install psycopg2-binary`
5. Migrate data
6. Restart service

## Troubleshooting

### Service won't start

```bash
# Check logs
sudo journalctl -u jaip -n 50

# Check if port is already in use
sudo netstat -tlnp | grep 8002

# Check permissions
ls -la /var/www/ai_journal
```

### Database errors

```bash
# Check file permissions
ls -la /var/www/ai_journal/data/

# Ensure www-data can write
sudo chown www-data:www-data /var/www/ai_journal/data/jaip.db
sudo chmod 664 /var/www/ai_journal/data/jaip.db
```

### Nginx errors

```bash
# Test configuration
sudo nginx -t

# Check error log
sudo tail -f /var/log/nginx/error.log
```

### File upload issues

```bash
# Check nginx client_max_body_size
grep client_max_body_size /etc/nginx/sites-available/jaip

# Check application MAX_FILE_SIZE_MB in .env
```

## Security Checklist

- [ ] DEBUG=False in production .env
- [ ] Strong SECRET_KEY generated
- [ ] HTTPS enabled with valid SSL certificate
- [ ] Firewall configured (UFW)
- [ ] Regular backups configured
- [ ] Log rotation configured
- [ ] File upload limits set
- [ ] ORCID production credentials configured
- [ ] Security headers enabled in Nginx
- [ ] Proper file permissions set
- [ ] Service runs as www-data (not root)

## Post-Deployment

1. Test all functionality:
   - ORCID login
   - Paper submission
   - PDF viewing
   - Comments and voting
   - Version updates

2. Monitor logs for first 24 hours

3. Set up monitoring/alerting (optional)

4. Configure regular backups

5. Document any custom configurations
