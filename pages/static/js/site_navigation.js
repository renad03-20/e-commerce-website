(() => {
    const button = document.querySelector('.mobile-menu-toggle');
    const menu = document.getElementById('site-navigation');
    if (!button || !menu) return;
    const closeMenu = () => {
        menu.classList.remove('show');
        button.setAttribute('aria-expanded', 'false');
    };
    button.addEventListener('click', () => {
        const open = menu.classList.toggle('show');
        button.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && menu.classList.contains('show')) {
            closeMenu();
            button.focus();
        }
    });
})();
