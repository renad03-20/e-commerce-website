(() => {
    const header = document.querySelector('.site-header');
    if (!header) return;
    const button = header.querySelector('.site-menu-toggle');
    const navigation = header.querySelector('#site-navigation');
    const account = header.querySelector('.site-account');
    const summary = account?.querySelector('summary');
    const mobile = window.matchMedia('(max-width: 760px)');
    header.classList.add('has-js');

    const closeNavigation = () => {
        navigation?.classList.remove('show');
        button?.setAttribute('aria-expanded', 'false');
        button?.setAttribute('aria-label', 'Open navigation');
    };
    const closeAccount = () => {
        if (account) account.open = false;
    };
    button?.addEventListener('click', () => {
        const open = navigation?.classList.toggle('show') ?? false;
        button.setAttribute('aria-expanded', String(open));
        button.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
        if (open) closeAccount();
    });
    navigation?.addEventListener('click', event => {
        if (event.target.closest('a')) closeNavigation();
    });
    summary?.addEventListener('click', () => {
        if (!account.open) closeNavigation();
    });
    account?.addEventListener('toggle', () => {
        if (account.open) closeNavigation();
    });
    account?.addEventListener('focusout', () => {
        window.requestAnimationFrame(() => {
            if (!account.contains(document.activeElement)) closeAccount();
        });
    });
    document.addEventListener('click', event => {
        if (!account?.contains(event.target)) closeAccount();
        if (!header.contains(event.target)) closeNavigation();
    });
    document.addEventListener('keydown', event => {
        if (event.key !== 'Escape') return;
        if (account?.open) {
            closeAccount();
            summary?.focus();
        } else if (navigation?.classList.contains('show')) {
            closeNavigation();
            button?.focus();
        }
    });
    mobile.addEventListener('change', closeNavigation);
})();
