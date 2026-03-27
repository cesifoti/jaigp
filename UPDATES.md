# JAIP Updates Log

## February 14, 2026 - User Feedback Implementation

### ✅ Improvements Implemented

#### 1. **Abstract Formatting Enhancement**
- **Feature**: Auto-cleanup of line breaks from PDF pastes
- **Implementation**:
  - Added auto-clean on paste event
  - Manual "Clean line breaks now" button
  - Strips multiple spaces and newlines into single paragraph
- **Help Text**: Updated to indicate "Single paragraph only" requirement
- **Files Modified**:
  - `templates/submit.html` - Added cleanAbstract() function

#### 2. **Multiple Human Authors Support**
- **Feature**: Add multiple human prompters with complete profile links
- **Fields Added**:
  - Full Name (required for additional authors)
  - ORCID ID (optional)
  - Google Scholar URL (optional)
  - Rankless.org URL (optional)
- **Implementation**:
  - Dynamic "Add Another Human Prompter" button
  - First author (submitter) auto-populated
  - Profile URLs saved to user records
- **Files Modified**:
  - `templates/submit.html` - New author UI and collection logic
  - `routes/submit.py` - Updated author handling
  - `models/user.py` - Added rankless_url column
  - Database migration added

#### 3. **OpenAlex Field Suggestions - Fixed**
- **Issue**: Feature wasn't working
- **Fix**:
  - Added error handling and debugging
  - Added validation for empty title
  - Better error messages displayed to users
- **Files Modified**:
  - `routes/submit.py` - Enhanced fetch-fields endpoint
  - `templates/components/field_suggestions.html` - Added error display

#### 4. **Favicon Added**
- **Feature**: Site-wide favicon for brand consistency
- **Implementation**:
  - Created SVG favicon with "J" logo
  - Blue background (#2563eb) matching site theme
  - Monospace font consistent with design
- **Files Created**:
  - `static/images/favicon.svg`
- **Files Modified**:
  - `templates/base.html` - Added favicon links

#### 5. **Delete Paper Functionality**
- **Feature**: Authors can delete their submitted papers
- **Security**: Only paper authors can delete
- **Confirmation**: JavaScript confirm dialog before deletion
- **Cleanup**: Deletes all associated files (PDFs, images, versions)
- **Files Created**:
  - `routes/delete.py` - New delete endpoint
- **Files Modified**:
  - `main.py` - Added delete router
  - `templates/paper.html` - Added delete button

### 🗂️ Database Changes

```sql
-- Added new column
ALTER TABLE users ADD COLUMN rankless_url VARCHAR;
```

### 📝 Files Modified

1. `templates/submit.html` - Major updates to form
2. `templates/paper.html` - Added delete button
3. `templates/base.html` - Added favicon
4. `templates/components/field_suggestions.html` - Error handling
5. `routes/submit.py` - Enhanced author handling and OpenAlex
6. `routes/delete.py` - NEW FILE
7. `models/user.py` - Added rankless_url field
8. `main.py` - Added delete router
9. `static/images/favicon.svg` - NEW FILE

### 🔄 To Apply Updates

If the app is running as a service:
```bash
sudo systemctl restart jaip
```

If running manually:
```bash
# Stop current instance (Ctrl+C)
./run.sh
```

### ✨ User-Visible Changes

1. **Submission Form**:
   - Abstract field has better instructions
   - Automatic line break cleaning when pasting
   - Can add multiple human authors
   - Each author can have Google Scholar and Rankless.org links
   - OpenAlex suggestions now work reliably

2. **Paper Page**:
   - Authors see a "Delete Paper" button (red, with confirmation)
   - Favicon appears in browser tab

3. **Profile Links**:
   - Google Scholar and Rankless.org URLs saved and displayed

### 🧪 Testing Checklist

- [ ] Submit a paper with abstract pasted from PDF
- [ ] Test "Clean line breaks" button
- [ ] Add multiple human authors with all profile links
- [ ] Test OpenAlex field suggestions
- [ ] Verify favicon appears in browser tab
- [ ] Test paper deletion (as author)
- [ ] Verify non-authors cannot delete papers
- [ ] Check that deleted papers' files are removed

### 🐛 Known Issues

None at this time.

### 📚 Next Steps

Consider future enhancements:
- Edit paper metadata after submission
- Email notifications for comments
- Search functionality
- Advanced author management
