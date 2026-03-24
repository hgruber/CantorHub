# Claude Code Configuration for CantorHub

## Project Overview

This is a Django-based web application for managing a cantor (choral) organization, likely used by a church or music group. The project includes functionality for managing members, events, songs, and communication forums.

## Key Components

### Core Models
- **User**: Extended Django User model with additional fields for member information
- **Artikel**: Articles/news items
- **Forum**: Discussion forums
- **Mitteilung**: Messages within forums
- **Ort**: Locations
- **Termin**: Events/performances
- **Lied**: Songs with various metadata
- **Konzert**: Concert programs linking songs to events
- **Zusage**: Attendance responses to events
- **Abstimmung**: Voting/decision tracking
- **TabellenPreferenzen**: Table column preferences for users

### Key Features
- Member management with voice types (soprano, alto, tenor, bass)
- Event management with attendance tracking
- Song database with file attachments
- Forum system for communication
- File management through django-filer
- Custom password hashing for legacy compatibility

## Technical Details

### Django Configuration
- Uses SQLite database (db.sqlite3)
- Custom User model extending AbstractUser
- Admin interface configured for all models
- Uses django-filer for file management
- Uses django-tables2 for table display
- Custom password hashers including PHP_PBKDF2Hasher for legacy compatibility

### File Structure
- `intern/` - Main application directory with models, admin, forms
- `config/` - Django settings and URLs
- `Avatare/` - Directory for member avatars
- `media/` - Uploaded files
- `static/` - Static assets
- `templates/` - HTML templates

### Setup
The project includes setup scripts:
- `start.sh` - For production deployment
- `migrate.sh` - For development setup
- `manage.py` - Django management commands

## Environment Variables
- DEBUG: Set to '1' for development
- SECRET_KEY: Django secret key (hardcoded in settings.py)

## Important Notes
1. The project has a custom password hasher for legacy PHP compatibility (`PHP_PBKDF2Hasher`)
2. Uses django-filer for file management with various folder types (avatars, articles, music, etc.)
3. Includes custom table management features with column preferences
4. Has a complex data model for managing musical performances and member attendance

## Usage
To run locally:
1. Set up virtual environment
2. Install dependencies from requirements.txt
3. Run `./migrate.sh` for development setup
4. Access at http://localhost:8000

To run in production:
1. Run `./start.sh`
2. Configure nginx and gunicorn as specified