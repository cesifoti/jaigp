# JAIP Production Deployment Guide
## For jaigp.org and jaigp.com

This guide will help you deploy JAIP to production using the automated deployment script.

## 🚀 Quick Deployment (Automated)

### Prerequisites

1. **Server Requirements**:
   - Ubuntu 20.04+ or Debian 11+
   - Root or sudo access
   - Public IP address
   - At least 2GB RAM, 20GB disk space

2. **DNS Configuration**:
   Before running the deployment script, configure your DNS:

   ```
   Type    Name              Value (Points to)
   ────────────────────────────────────────────────
   A       jaigp.org         YOUR_SERVER_IP
   A       jaigp.com         YOUR_SERVER_IP
   A       www.jaigp.org     YOUR_SERVER_IP
   A       www.jaigp.com     YOUR_SERVER_IP
   ```

   **How to find your server IP**:
   ```bash
   curl ifconfig.me
   ```

3. **ORCID Credentials** (Optional but recommended):
   - Go to https://orcid.org/developer-tools
   - Click "Register for the free ORCID public API"
   - Fill in details:
     - Redirect URI: `https://jaigp.org/auth/callback`
   - Save your Client ID and Client Secret

### One-Command Deployment

```bash
sudo ./deploy.sh
```

That's it! The script will:
- ✅ Check all prerequisites
- ✅ Configure production environment
- ✅ Set up systemd service
- ✅ Configure nginx for both domains
- ✅ Obtain SSL certificates
- ✅ Configure firewall
- ✅ Start all services
- ✅ Set up automated backups

### What the Script Does

#### 1. Prerequisites Check
- Verifies Python 3 is installed
- Checks/installs nginx
- Checks/installs certbot
- Verifies virtual environment exists

#### 2. Environment Configuration
- Generates secure SECRET_KEY
- Prompts for ORCID credentials
- Creates production `.env` file
- Configures URLs for jaigp.org

#### 3. Service Setup
- Creates systemd service at `/etc/systemd/system/jaip.service`
- Configures auto-restart on failure
- Sets proper security restrictions

#### 4. Nginx Configuration
- Creates config for both domains (jaigp.org and jaigp.com)
- Sets up HTTP to HTTPS redirect
- Redirects jaigp.com → jaigp.org
- Configures SSL/TLS settings
- Sets security headers
- Optimizes for file uploads

#### 5. SSL Certificates
- Obtains Let's Encrypt certificates for:
  - jaigp.org
  - jaigp.com
  - www.jaigp.org
  - www.jaigp.com
- Configures auto-renewal

#### 6. Firewall Setup
- Enables UFW firewall
- Allows SSH (port 22)
- Allows HTTP (port 80)
- Allows HTTPS (port 443)

#### 7. Automated Backups
- Daily database backups at 2 AM
- Daily file backups
- Keeps last 7 days of backups
- Stored in `/var/backups/jaip/`

## 📋 During Deployment

The script will prompt you for:

1. **ORCID Client ID** (optional):
   ```
   Enter ORCID Client ID (or press Enter to skip): APP-XXXXXXXXXXXX
   ```

2. **ORCID Client Secret** (optional):
   ```
   Enter ORCID Client Secret (or press Enter to skip): xxxx-xxxx-xxxx
   ```

3. **Admin Email** (required for SSL):
   ```
   Enter admin email for OpenAlex API: admin@jaigp.org
   ```

4. **DNS Confirmation**:
   ```
   Are all domains configured in DNS? (y/n): y
   ```

## ✅ Post-Deployment

After successful deployment, you'll see:

```
═══════════════════════════════════════════════════════════
DEPLOYMENT COMPLETE!
═══════════════════════════════════════════════════════════

Your JAIP instance is now running at:
  • Primary: https://jaigp.org
  • Secondary: https://jaigp.com (redirects to .org)
```

### Verify Everything is Working

1. **Check Services**:
   ```bash
   sudo systemctl status jaip
   sudo systemctl status nginx
   ```

2. **View Logs**:
   ```bash
   # Application logs
   sudo journalctl -u jaip -f

   # Nginx access logs
   sudo tail -f /var/log/nginx/jaip_access.log

   # Nginx error logs
   sudo tail -f /var/log/nginx/jaip_error.log
   ```

3. **Test Website**:
   - Visit https://jaigp.org
   - Try https://jaigp.com (should redirect to .org)
   - Test ORCID login if configured
   - Submit a test paper

## 🔧 Manual Configuration (If Needed)

### Update ORCID Credentials

If you skipped ORCID setup or need to update:

```bash
sudo nano /var/www/ai_journal/.env
```

Update these lines:
```env
ORCID_CLIENT_ID=your-new-client-id
ORCID_CLIENT_SECRET=your-new-secret
```

Then restart:
```bash
sudo systemctl restart jaip
```

### Manual SSL Setup

If SSL was skipped during deployment:

```bash
sudo certbot --nginx \
  -d jaigp.org \
  -d jaigp.com \
  -d www.jaigp.org \
  -d www.jaigp.com
```

## 🛠️ Common Tasks

### Restart Application
```bash
sudo systemctl restart jaip
```

### View Real-time Logs
```bash
sudo journalctl -u jaip -f
```

### Update Application
```bash
cd /var/www/ai_journal
git pull  # if using git
source venv/bin/activate
pip install -r requirements.txt --upgrade
sudo systemctl restart jaip
```

### Manual Backup
```bash
sudo /usr/local/bin/backup-jaip.sh
```

### Restore from Backup
```bash
# Stop service
sudo systemctl stop jaip

# Restore database
sudo cp /var/backups/jaip/jaip_YYYYMMDD_HHMMSS.db /var/www/ai_journal/data/jaip.db

# Restore files
sudo tar -xzf /var/backups/jaip/papers_YYYYMMDD_HHMMSS.tar.gz -C /

# Fix permissions
sudo chown -R www-data:www-data /var/www/ai_journal/data

# Start service
sudo systemctl start jaip
```

## 🔒 Security Checklist

After deployment, verify:

- ✅ HTTPS is working (green padlock in browser)
- ✅ HTTP redirects to HTTPS
- ✅ DEBUG=False in .env
- ✅ Strong SECRET_KEY generated
- ✅ Firewall is active (ufw status)
- ✅ Services run as www-data (not root)
- ✅ File permissions are correct (600 for .env)
- ✅ SSL certificate auto-renewal works
- ✅ Backups are running daily

## 📊 Monitoring

### Check Service Status
```bash
sudo systemctl status jaip
```

### Check Resource Usage
```bash
htop
df -h
free -h
```

### Check Nginx Status
```bash
sudo nginx -t                    # Test configuration
sudo systemctl status nginx      # Service status
```

### SSL Certificate Status
```bash
sudo certbot certificates
```

## 🚨 Troubleshooting

### Service Won't Start
```bash
# Check logs
sudo journalctl -u jaip -n 100

# Check if port is in use
sudo netstat -tlnp | grep 8002

# Verify permissions
ls -la /var/www/ai_journal/data/
```

### SSL Certificate Issues
```bash
# Check certificate status
sudo certbot certificates

# Renew manually
sudo certbot renew --force-renewal

# Check nginx config
sudo nginx -t
```

### 502 Bad Gateway
Usually means the app isn't running:
```bash
sudo systemctl status jaip
sudo journalctl -u jaip -n 50
sudo systemctl restart jaip
```

### File Upload Errors
Check nginx max upload size:
```bash
sudo grep client_max_body_size /etc/nginx/sites-available/jaip
```

### ORCID Login Not Working
1. Verify credentials in .env
2. Check redirect URI matches ORCID settings exactly
3. Check application logs for errors

## 🔄 Updating

To update the application:

1. **Backup first**:
   ```bash
   sudo /usr/local/bin/backup-jaip.sh
   ```

2. **Update code**:
   ```bash
   cd /var/www/ai_journal
   # Update your code (git pull, etc.)
   ```

3. **Update dependencies**:
   ```bash
   source venv/bin/activate
   pip install -r requirements.txt --upgrade
   ```

4. **Restart**:
   ```bash
   sudo systemctl restart jaip
   ```

## 📞 Support Files

- **Main docs**: `/var/www/ai_journal/README.md`
- **This guide**: `/var/www/ai_journal/DEPLOYMENT_GUIDE.md`
- **Nginx config**: `/etc/nginx/sites-available/jaip`
- **Service file**: `/etc/systemd/system/jaip.service`
- **Environment**: `/var/www/ai_journal/.env`

## 🎉 Success Criteria

Your deployment is successful when:

1. ✅ https://jaigp.org loads without errors
2. ✅ SSL certificate is valid (green padlock)
3. ✅ ORCID login works (if configured)
4. ✅ You can submit a test paper
5. ✅ Comments and voting work
6. ✅ All pages are responsive on mobile
7. ✅ Services survive a server reboot

---

**Congratulations!** Your JAIP instance is now live at https://jaigp.org! 🚀

*"We are not sure if these papers are good, after all, we are only human."*
