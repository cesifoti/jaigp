// Client-side utilities for JAIP

// Mobile menu toggle — handled in nav.html inline script

// Toast notification system
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast bg-white shadow-lg rounded-lg border-l-4 p-4 ${
        type === 'success' ? 'border-accent' :
        type === 'error' ? 'border-red-500' :
        'border-primary'
    }`;

    toast.innerHTML = `
        <div class="flex items-center">
            <div class="flex-1">
                <p class="text-sm font-medium text-slate-900">${message}</p>
            </div>
            <button onclick="this.parentElement.parentElement.remove()" class="ml-4 text-slate-400 hover:text-slate-600">
                <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                    <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"></path>
                </svg>
            </button>
        </div>
    `;

    document.body.appendChild(toast);

    // Auto-remove after 5 seconds
    setTimeout(() => {
        toast.remove();
    }, 5000);
}

// Handle HTMX errors
document.body.addEventListener('htmx:responseError', function(event) {
    showToast('An error occurred. Please try again.', 'error');
});

// Handle HTMX success
document.body.addEventListener('htmx:afterSwap', function(event) {
    // Check if the response contains a success message
    const successMsg = event.detail.xhr.getResponseHeader('X-Success-Message');
    if (successMsg) {
        showToast(successMsg, 'success');
    }
});

// File upload preview
function previewFile(input, previewElementId) {
    const file = input.files[0];
    const preview = document.getElementById(previewElementId);

    if (file && preview) {
        const reader = new FileReader();

        reader.onload = function(e) {
            if (file.type.startsWith('image/')) {
                preview.innerHTML = `<img src="${e.target.result}" class="max-w-full h-auto rounded-lg" alt="Preview">`;
            } else if (file.type === 'application/pdf') {
                preview.innerHTML = `<p class="text-sm text-slate-600">PDF selected: ${file.name}</p>`;
            }
        };

        reader.readAsDataURL(file);
    }
}

// Character counter for textareas
function setupCharCounter(textareaId, counterId, maxLength) {
    const textarea = document.getElementById(textareaId);
    const counter = document.getElementById(counterId);

    if (textarea && counter) {
        textarea.addEventListener('input', function() {
            const remaining = maxLength - this.value.length;
            counter.textContent = `${remaining} characters remaining`;

            if (remaining < 0) {
                counter.classList.add('text-red-500');
            } else {
                counter.classList.remove('text-red-500');
            }
        });
    }
}

// Confirm before destructive actions
function confirmAction(message) {
    return confirm(message);
}

// Copy to clipboard
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(function() {
        showToast('Copied to clipboard!', 'success');
    }, function() {
        showToast('Failed to copy', 'error');
    });
}

// Format date helper
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    });
}

// Debounce helper
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}
