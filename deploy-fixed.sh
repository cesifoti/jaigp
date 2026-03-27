#!/bin/bash
#
# JAIP Automated Deployment Script (FIXED)
# For jaigp.org and jaigp.com
#
# This script handles SSL certificate setup properly
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
APP_DIR="/var/www/ai_journal"
APP_USER="www-data"
APP_GROUP="www-data"
PRIMARY_DOMAIN="jaigp.org"
SECONDARY_DOMAIN="jaigp.com"
APP_PORT="8002"
WORKERS="3"

# Functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check if running on Ubuntu/Debian
    if [ ! -f /etc/debian_version ]; then
        log_warning "This script is designed for Ubuntu/Debian. Continue anyway? (y/n)"
        read -r response
        if [[ ! "$response" =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi

    # Check Python
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is not installed"
        exit 1
    fi

    # Check nginx
    if ! command -v nginx &> /dev/null; then
        log_warning "Nginx is not installed. Install it? (y/n)"
        read -r response
        if [[ "$response" =~ ^[Yy]$ ]]; then
            apt update
            apt install -y nginx
        else
            log_error "Nginx is required for deployment"
            exit 1
        fi
    fi

    # Check certbot
    if ! command -v certbot &> /dev/null; then
        log_warning "Certbot is not installed. Install it? (y/n)"
        read -r response
        if [[ "$response" =~ ^[Yy]$ ]]; then
            apt update
            apt install -y certbot python3-certbot-nginx
        else
            log_warning "Certbot is recommended for SSL certificates"
        fi
    fi

    # Check if venv exists
    if [ ! -d "$APP_DIR/venv" ]; then
        log_error "Virtual environment not found at $APP_DIR/venv"
        exit 1
    fi

    log_success "All prerequisites met"
}

setup_systemd() {
    log_info "Creating systemd service..."

    cat > /etc/systemd/system/jaip.service <<EOF
[Unit]
Description=JAIP - Journal for AI Generated Papers
After=network.target

[Service]
User=$APP_USER
Group=$APP_GROUP
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin"
ExecStart=$APP_DIR/venv/bin/uvicorn main:app --workers $WORKERS --host 127.0.0.1 --port $APP_PORT

# Restart policy
Restart=always
RestartSec=10

# Security
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP_DIR/data
ReadOnlyPaths=$APP_DIR

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=jaip

[Install]
WantedBy=multi-user.target
EOF

    log_success "Systemd service created"
}

setup_nginx_http_only() {
    log_info "Creating nginx configuration (HTTP only for now)..."

    # Create HTTP-only config first (for Let's Encrypt validation)
    cat > /etc/nginx/sites-available/jaip <<'EOF'
# HTTP - For Let's Encrypt validation and redirect
server {
    listen 80;
    listen [::]:80;
    server_name jaigp.org jaigp.com www.jaigp.org www.jaigp.com;

    # Let's Encrypt validation
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    # Proxy to application (temporary, will redirect to HTTPS after SSL setup)
    location / {
        proxy_pass http://127.0.0.1:8002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Static files
    location /static/ {
        alias /var/www/ai_journal/static/;
        expires 30d;
    }
}
EOF

    # Enable site
    ln -sf /etc/nginx/sites-available/jaip /etc/nginx/sites-enabled/

    # Test nginx configuration
    nginx -t

    log_success "Nginx HTTP configuration created"
}

setup_nginx_https() {
    log_info "Updating nginx configuration for HTTPS..."

    # Create full HTTPS config
    cat > /etc/nginx/sites-available/jaip <<'EOF'
# HTTP - Redirect to HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name jaigp.org jaigp.com www.jaigp.org www.jaigp.com;

    # Let's Encrypt validation
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    # Redirect to HTTPS
    location / {
        return 301 https://jaigp.org$request_uri;
    }
}

# HTTPS - Secondary domains redirect to primary
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name jaigp.com www.jaigp.com www.jaigp.org;

    # SSL certificates
    ssl_certificate /etc/letsencrypt/live/jaigp.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/jaigp.org/privkey.pem;

    # Redirect to primary domain
    return 301 https://jaigp.org$request_uri;
}

# HTTPS - Primary domain
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name jaigp.org;

    # SSL certificates
    ssl_certificate /etc/letsencrypt/live/jaigp.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/jaigp.org/privkey.pem;

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

        # Timeouts
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    # Static files
    location /static/ {
        alias /var/www/ai_journal/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Logging
    access_log /var/log/nginx/jaip_access.log;
    error_log /var/log/nginx/jaip_error.log;
}
EOF

    # Test nginx configuration
    nginx -t

    log_success "Nginx HTTPS configuration updated"
}

set_permissions() {
    log_info "Setting file permissions..."

    # Set ownership
    chown -R $APP_USER:$APP_GROUP $APP_DIR

    # Set directory permissions
    chmod -R 755 $APP_DIR
    chmod -R 775 $APP_DIR/data
    chmod 600 $APP_DIR/.env

    # Make run script executable
    chmod +x $APP_DIR/run.sh 2>/dev/null || true

    log_success "Permissions set"
}

configure_firewall() {
    log_info "Configuring firewall..."

    if command -v ufw &> /dev/null; then
        # Enable UFW if not already enabled
        ufw --force enable

        # Allow SSH (important!)
        ufw allow ssh

        # Allow HTTP and HTTPS
        ufw allow 'Nginx Full'

        # Show status
        ufw status

        log_success "Firewall configured"
    else
        log_warning "UFW not installed. Please configure firewall manually"
    fi
}

start_services() {
    log_info "Starting services..."

    # Reload systemd
    systemctl daemon-reload

    # Enable and start JAIP service
    systemctl enable jaip
    systemctl restart jaip

    # Restart nginx
    systemctl restart nginx

    # Wait a moment
    sleep 3

    # Check status
    if systemctl is-active --quiet jaip; then
        log_success "JAIP service is running"
    else
        log_error "JAIP service failed to start. Check logs with: journalctl -u jaip -n 50"
        journalctl -u jaip -n 20
        exit 1
    fi

    if systemctl is-active --quiet nginx; then
        log_success "Nginx is running"
    else
        log_error "Nginx failed to start. Check logs with: journalctl -u nginx -n 50"
        exit 1
    fi
}

setup_ssl() {
    log_info "Setting up SSL certificates..."

    echo ""
    log_warning "DNS Configuration Check"
    echo "Your server IP: $(curl -s ifconfig.me 2>/dev/null || echo 'Unable to detect')"
    echo ""
    echo "Ensure these domains point to your server:"
    echo "  - jaigp.org"
    echo "  - jaigp.com"
    echo "  - www.jaigp.org"
    echo "  - www.jaigp.com"
    echo ""
    read -p "Are all domains configured in DNS? (y/n): " dns_ready

    if [[ ! "$dns_ready" =~ ^[Yy]$ ]]; then
        log_warning "Skipping SSL setup. Your site is available at:"
        echo "  http://jaigp.org (and other domains)"
        echo ""
        echo "To set up SSL later, run:"
        echo "  sudo certbot --nginx -d jaigp.org -d jaigp.com -d www.jaigp.org -d www.jaigp.com"
        return
    fi

    # Read admin email from .env if not already set
    if [ -z "$ADMIN_EMAIL" ]; then
        ADMIN_EMAIL=$(grep OPENALEX_API_EMAIL $APP_DIR/.env | cut -d '=' -f2)
    fi

    # Get SSL certificates
    log_info "Obtaining SSL certificates..."
    certbot certonly --nginx \
        -d jaigp.org \
        -d jaigp.com \
        -d www.jaigp.org \
        -d www.jaigp.com \
        --non-interactive \
        --agree-tos \
        --email "$ADMIN_EMAIL" || {
        log_warning "SSL certificate setup failed"
        log_info "You can try again manually with:"
        echo "  sudo certbot --nginx -d jaigp.org -d jaigp.com -d www.jaigp.org -d www.jaigp.com"
        return
    }

    # Update nginx config to use HTTPS
    setup_nginx_https

    # Reload nginx
    systemctl reload nginx

    # Test auto-renewal
    certbot renew --dry-run || log_warning "SSL renewal test failed"

    log_success "SSL certificates configured"
}

setup_backups() {
    log_info "Setting up automated backups..."

    # Create backup directory
    mkdir -p /var/backups/jaip

    # Create backup script
    cat > /usr/local/bin/backup-jaip.sh <<'EOF'
#!/bin/bash
BACKUP_DIR="/var/backups/jaip"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# Backup database
cp /var/www/ai_journal/data/jaip.db $BACKUP_DIR/jaip_$DATE.db

# Backup papers directory
tar -czf $BACKUP_DIR/papers_$DATE.tar.gz /var/www/ai_journal/data/papers 2>/dev/null

# Keep only last 7 days of backups
find $BACKUP_DIR -name "jaip_*.db" -mtime +7 -delete
find $BACKUP_DIR -name "papers_*.tar.gz" -mtime +7 -delete

echo "Backup completed: $DATE"
EOF

    chmod +x /usr/local/bin/backup-jaip.sh

    # Add to crontab for www-data user
    (crontab -u $APP_USER -l 2>/dev/null; echo "0 2 * * * /usr/local/bin/backup-jaip.sh >> /var/log/jaip-backup.log 2>&1") | crontab -u $APP_USER -

    log_success "Automated backups configured (daily at 2 AM)"
}

print_summary() {
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    log_success "DEPLOYMENT COMPLETE!"
    echo "═══════════════════════════════════════════════════════════"
    echo ""

    if [ -f /etc/letsencrypt/live/jaigp.org/fullchain.pem ]; then
        echo "Your JAIP instance is now running at:"
        echo "  • Primary: https://jaigp.org"
        echo "  • Secondary: https://jaigp.com (redirects to .org)"
    else
        echo "Your JAIP instance is now running at:"
        echo "  • http://jaigp.org (HTTP only - SSL not configured)"
        echo ""
        log_warning "To enable HTTPS, run:"
        echo "  sudo certbot --nginx -d jaigp.org -d jaigp.com -d www.jaigp.org -d www.jaigp.com"
    fi

    echo ""
    echo "Service Status:"
    echo "  • JAIP Application: $(systemctl is-active jaip)"
    echo "  • Nginx Web Server: $(systemctl is-active nginx)"
    echo ""
    echo "Useful Commands:"
    echo "  • View app logs: sudo journalctl -u jaip -f"
    echo "  • View nginx logs: sudo tail -f /var/log/nginx/jaip_access.log"
    echo "  • Restart app: sudo systemctl restart jaip"
    echo "  • Check status: sudo systemctl status jaip"
    echo ""
    echo "Configuration Files:"
    echo "  • App config: $APP_DIR/.env"
    echo "  • Systemd service: /etc/systemd/system/jaip.service"
    echo "  • Nginx config: /etc/nginx/sites-available/jaip"
    echo ""
    echo "═══════════════════════════════════════════════════════════"
}

# Main deployment process
main() {
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo "  JAIP - Automated Deployment Script"
    echo "  Deploying to: jaigp.org & jaigp.com"
    echo "═══════════════════════════════════════════════════════════"
    echo ""

    check_root
    check_prerequisites

    echo ""
    log_info "Using existing .env configuration"
    log_info "ORCID Client ID: $(grep ORCID_CLIENT_ID $APP_DIR/.env | cut -d '=' -f2)"
    echo ""

    log_warning "This will deploy JAIP to production. Continue? (y/n)"
    read -r confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        log_info "Deployment cancelled"
        exit 0
    fi

    set_permissions
    setup_systemd
    setup_nginx_http_only  # HTTP only first
    configure_firewall
    start_services
    setup_ssl  # This will upgrade to HTTPS if DNS is ready
    setup_backups

    print_summary
}

# Run main function
main "$@"
