document.querySelectorAll('form[data-confirm]').forEach(form => {
  form.addEventListener('submit', event => {
    const text = form.getAttribute('data-confirm') || 'Подтвердить действие?';
    if (!confirm(text)) event.preventDefault();
  });
});

function bindButtonRipple() {
  const selector = '.btn, .action-btn, .logout-link, .nav a, input[type="submit"]';
  document.querySelectorAll(selector).forEach(button => {
    button.addEventListener('mousemove', event => {
      const rect = button.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      button.style.setProperty('--mouse-x', `${x}px`);
      button.style.setProperty('--mouse-y', `${y}px`);
    });
  });
}

bindButtonRipple();

setTimeout(() => {
  document.querySelectorAll('.alert').forEach(alert => {
    alert.style.transition = '0.35s ease';
    alert.style.opacity = '0';
    alert.style.transform = 'translateY(-6px)';
  });
}, 4000);


function initThemeToggle() {
  const button = document.getElementById('themeToggle');
  if (!button) return;

  const savedTheme = localStorage.getItem('portal-theme') || 'light';
  document.body.classList.toggle('dark-theme', savedTheme === 'dark');
  button.textContent = savedTheme === 'dark' ? 'Светлая тема' : 'Тёмная тема';

  button.addEventListener('click', () => {
    const isDark = document.body.classList.toggle('dark-theme');
    localStorage.setItem('portal-theme', isDark ? 'dark' : 'light');
    button.textContent = isDark ? 'Светлая тема' : 'Тёмная тема';
  });
}

function initScrollTopButton() {
  const button = document.getElementById('scrollTopBtn');
  if (!button) return;

  const toggleVisibility = () => {
    button.classList.toggle('visible', window.scrollY > 360);
  };

  window.addEventListener('scroll', toggleVisibility, { passive: true });
  toggleVisibility();

  button.addEventListener('click', () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
}

initThemeToggle();
initScrollTopButton();


function initImportantToast() {
  const toast = document.getElementById('importantNewsToast');
  if (!toast) return;

  const postId = toast.dataset.postId;
  const storageKey = 'portal-last-important-toast';
  const closeBtn = document.getElementById('toastCloseBtn');
  const openLink = toast.querySelector('a');

  const closeToast = () => {
    toast.classList.remove('visible');
    localStorage.setItem(storageKey, postId);
  };

  if (localStorage.getItem(storageKey) !== postId) {
    window.setTimeout(() => toast.classList.add('visible'), 700);
  }

  if (closeBtn) closeBtn.addEventListener('click', closeToast);
  if (openLink) openLink.addEventListener('click', () => localStorage.setItem(storageKey, postId));
}

initImportantToast();
