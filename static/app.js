document.addEventListener('DOMContentLoaded', function() {
    // Confirmation before destructive actions
    document.querySelectorAll('form[data-confirm]').forEach(function(form) {
        form.addEventListener('submit', function(e) {
            if (!confirm(form.dataset.confirm)) {
                e.preventDefault();
            }
        });
    });

    // CSV import: the visible button opens the hidden file input, selecting a file submits
    document.querySelectorAll('[data-file-trigger]').forEach(function(button) {
        const input = document.getElementById(button.dataset.fileTrigger);
        button.addEventListener('click', function() {
            input.click();
        });
        input.addEventListener('change', function() {
            input.form.submit();
        });
    });

    // PDF modals
    document.querySelectorAll('[data-modal-open]').forEach(function(button) {
        const modal = document.getElementById(button.dataset.modalOpen);
        button.addEventListener('click', function() {
            const dateInput = modal.querySelector('input[type="date"]');
            const today = new Date();
            const localDate = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');
            dateInput.value = localDate;
            dateInput.min = localDate;
            modal.classList.remove('hidden');
        });
    });
    document.querySelectorAll('[data-modal]').forEach(function(modal) {
        modal.querySelector('form').addEventListener('submit', function() {
            modal.classList.add('hidden');
        });
        modal.querySelector('[data-modal-close]').addEventListener('click', function() {
            modal.classList.add('hidden');
        });
    });

    // Event form: season selection controls the date fields
    const seasonSelect = document.getElementById('season');
    if (seasonSelect) {
        const startInput = document.getElementById('start_date');
        const endInput = document.getElementById('end_date');
        const summerStart = seasonSelect.dataset.summerStart;
        const winterStart = seasonSelect.dataset.winterStart;

        function updateFields() {
            const val = seasonSelect.value;
            const manual = val === 'Manuell';
            if (val === 'Immer') {
                startInput.value = '';
                endInput.value = '';
            } else if (val === 'Sommer') {
                startInput.value = summerStart;
                endInput.value = winterStart;
            } else if (val === 'Winter') {
                startInput.value = winterStart;
                endInput.value = summerStart;
            }
            [startInput, endInput].forEach(function(input) {
                input.readOnly = !manual;
                input.classList.toggle('bg-slate-100', !manual);
                input.classList.toggle('text-slate-500', !manual);
            });
        }

        seasonSelect.addEventListener('change', updateFields);

        // Init on page load (keeps manual dates, seasonal events always show the configured phases)
        updateFields();
    }
});
