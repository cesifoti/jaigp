#!/bin/bash
#
# JAIP Automated Deployment Script
# For jaigp.org and jaigp.com
#
# This script will:
# 1. Check prerequisites
# 2. Update production .env configuration
# 3. Create systemd service
# 4. Create nginx configuration
# 5. Set up SSL certificates
# 6. Configure firewall
# 7. Start services
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
            log_error "Certbot is required for SSL certificates"
            exit 1
        fi
    fi

    # Check if venv exists
    if [ ! -d "$APP_DIR/venv" ]; then
        log_error "Virtual environment not found at $APP_DIR/venv"
        exit 1
    fi

    log_success "All prerequisites met"
}

configure_environment() {
    log_info "Configuring production environment..."

    # Backup existing .env if it exists
    if [ -f "$APP_DIR/.env" ]; then
        cp "$APP_DIR/.env" "$APP_DIR/.env.backup.$(date +%Y%m%d_%H%M%S)"
        log_success "Backed up existing .env file"
    fi

    # Prompt for ORCID credentials
    echo ""
    log_warning "ORCID OAuth Configuration Required"
    echo "Please visit https://orcid.org/developer-tools to get your credentials"
    echo ""

    read -p "Enter ORCID Client ID (or press Enter to skip): " ORCID_CLIENT_ID
    read -p "Enter ORCID Client Secret (or press Enter to skip): " ORCID_CLIENT_SECRET

    # Generate secret key
    log_info "Generating secure SECRET_KEY..."
    SECRET_KEY=$(openssl rand -hex 32)

    # Prompt for admin email
    read -p "Enter admin email for OpenAlex API: " ADMIN_EMAIL

    # Create production .env
    cat > "$APP_DIR/.env" <<EOF
# Application
APP_NAME="JAIP - Journal for AI Generated Papers"
DEBUG=False
SECRET_KEY=$SECRET_KEY
BASE_URL=https://$PRIMARY_DOMAIN

# Database
DATABASE_URL=sqlite:///./data/jaip.db

# ORCID OAuth (Production)
ORCID_CLIENT_ID=${ORCID_CLIENT_ID:-APP-XXXXXXXXXX}
ORCID_CLIENT_SECRET=${ORCID_CLIENT_SECRET:-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}
ORCID_REDIRECT_URI=https://$PRIMARY_DOMAIN/auth/callback
ORCID_AUTH_URL=https://orcid.org/oauth/authorize
ORCID_TOKEN_URL=https://orcid.org/oauth/token
ORCID_API_URL=https://pub.orcid.org/v3.0

# OpenAlex
OPENALEX_API_EMAIL=${ADMIN_EMAIL:-admin@$PRIMARY_DOMAIN}
OPENALEX_API_URL=https://api.openalex.org

# File Storage
DATA_DIR=/var/www/ai_journal/data
MAX_FILE_SIZE_MB=50
ALLOWED_PDF_TYPES=application/pdf
ALLOWED_IMAGE_TYPES=image/jpeg,image/png,image/jpg

# Server
PORT=$APP_PORT
WORKERS=$WORKERS
HOST=127.0.0.1

# Session
SESSION_MAX_AGE=86400
SESSION_COOKIE_NAME=jaip_session
EOF

    chmod 600 "$APP_DIR/.env"
    log_success "Production .env configured"
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

setup_nginx() {
    log_info "Creating nginx configuration..."

    # Create nginx config
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

# HTTPS - Secondary domain redirect
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name jaigp.com www.jaigp.com www.jaigp.org;

    # SSL certificates (will be configured by certbot)
    ssl_certificate /etc/letsencrypt/live/jaigp.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/jaigp.org/privkey.pem;
    ssl_trusted_certificate /etc/letsencrypt/live/jaigp.org/chain.pem;

    # Redirect to primary domain
    return 301 https://jaigp.org$request_uri;
}

# HTTPS - Primary domain
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name jaigp.org;

    # SSL certificates (will be configured by certbot)
    ssl_certificate /etc/letsencrypt/live/jaigp.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/jaigp.org/privkey.pem;
    ssl_trusted_certificate /etc/letsencrypt/live/jaigp.org/chain.pem;

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
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

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
EOF

    # Enable site
    ln -sf /etc/nginx/sites-available/jaip /etc/nginx/sites-enabled/

    # Remove default site if exists
    if [ -f /etc/nginx/sites-enabled/default ]; then
        rm /etc/nginx/sites-enabled/default
    fi

    # Test nginx configuration
    nginx -t

    log_success "Nginx configuration created"
}

setup_ssl() {
    log_info "Setting up SSL certificates..."

    echo ""
    log_warning "DNS Configuration Check"
    echo "Before continuing, ensure your domains point to this server:"
    echo "  - jaigp.org → $(curl -s ifconfig.me)"
    echo "  - jaigp.com → $(curl -s ifconfig.me)"
    echo "  - www.jaigp.org → $(curl -s ifconfig.me)"
    echo "  - www.jaigp.com → $(curl -s ifconfig.me)"
    echo ""
    read -p "Are all domains configured in DNS? (y/n): " dns_ready

    if [[ ! "$dns_ready" =~ ^[Yy]$ ]]; then
        log_warning "Skipping SSL setup. You can run it later with:"
        echo "  sudo certbot --nginx -d jaigp.org -d jaigp.com -d www.jaigp.org -d www.jaigp.com"
        return
    fi

    # Get SSL certificates
    certbot --nginx \
        -d jaigp.org \
        -d jaigp.com \
        -d www.jaigp.org \
        -d www.jaigp.com \
        --non-interactive \
        --agree-tos \
        --redirect \
        --email "$ADMIN_EMAIL" || {
        log_warning "SSL certificate setup failed or was skipped"
        log_info "You can set it up manually later with:"
        echo "  sudo certbot --nginx -d jaigp.org -d jaigp.com -d www.jaigp.org -d www.jaigp.com"
    }

    # Test auto-renewal
    certbot renew --dry-run || log_warning "SSL renewal test failed"

    log_success "SSL certificates configured"
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
    chmod +x $APP_DIR/run.sh

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
    sleep 2

    # Check status
    if systemctl is-active --quiet jaip; then
        log_success "JAIP service is running"
    else
        log_error "JAIP service failed to start. Check logs with: journalctl -u jaip -n 50"
        exit 1
    fi

    if systemctl is-active --quiet nginx; then
        log_success "Nginx is running"
    else
        log_error "Nginx failed to start. Check logs with: journalctl -u nginx -n 50"
        exit 1
    fi
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
    echo "Your JAIP instance is now running at:"
    echo "  • Primary: https://jaigp.org"
    echo "  • Secondary: https://jaigp.com (redirects to .org)"
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
    echo "  • Manual backup: sudo /usr/local/bin/backup-jaip.sh"
    echo ""
    echo "Configuration Files:"
    echo "  • App config: $APP_DIR/.env"
    echo "  • Systemd service: /etc/systemd/system/jaip.service"
    echo "  • Nginx config: /etc/nginx/sites-available/jaip"
    echo ""

    if [ -z "$ORCID_CLIENT_ID" ] || [ "$ORCID_CLIENT_ID" == "APP-XXXXXXXXXX" ]; then
        log_warning "ORCID credentials not configured!"
        echo "  To enable authentication, get credentials from:"
        echo "  https://orcid.org/developer-tools"
        echo "  Then update $APP_DIR/.env and restart:"
        echo "  sudo systemctl restart jaip"
        echo ""
    fi

    echo "Next Steps:"
    echo "  1. Visit https://jaigp.org to see your site"
    echo "  2. Configure ORCID OAuth if not done (see above)"
    echo "  3. Monitor logs for the first 24 hours"
    echo "  4. Test all functionality (login, submit, comment)"
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
    log_warning "This will deploy JAIP to production. Continue? (y/n)"
    read -r confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        log_info "Deployment cancelled"
        exit 0
    fi

    configure_environment
    set_permissions
    setup_systemd
    setup_nginx
    configure_firewall
    start_services
    setup_ssl
    setup_backups

    print_summary
}

# Run main function
main "$@"
