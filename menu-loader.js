(() => {
  function ensureStylesheet(href) {
    if (document.querySelector(`link[href="${href}"]`)) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    document.head.append(link);
  }

  async function loadMenu() {
    ensureStylesheet('menu.css');
    ensureStylesheet('https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css');
    let placeholder = document.querySelector('[data-app-menu]');
    if (!placeholder) {
      placeholder = document.createElement('div');
      const page = location.pathname.split('/').pop().toLowerCase();
      const menuByPage = {
        'editcompany.html': 'company',
        'listcompany.html': 'company',
        'editcampaign.html': 'campaign',
        'listcampaign.html': 'campaign',
      };
      placeholder.dataset.appMenu = menuByPage[page] || 'home';
      const oldMenu = document.querySelector('nav[aria-label="Điều hướng chính"]');
      if (oldMenu) oldMenu.replaceWith(placeholder);
      else (document.querySelector('header') || document.body.firstChild).before(placeholder);
    }
    try {
      const response = await fetch('menu.html', { cache: 'no-cache' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      placeholder.innerHTML = await response.text();
      const active = placeholder.dataset.appMenu;
      const activeLink = placeholder.querySelector(`[data-menu="${CSS.escape(active)}"]`);
      if (activeLink) {
        activeLink.classList.add('active');
        activeLink.setAttribute('aria-current', 'page');
      }
    } catch (error) {
      console.error('Không tải được menu dùng chung.', error);
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', loadMenu);
  else loadMenu();
})();
