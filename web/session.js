(() => {
  localStorage.removeItem('token');
  const originalFetch = window.fetch.bind(window);
  function csrf() {
    const pair = document.cookie.split('; ').find(part => part.startsWith('__Host-pricesnap_csrf='));
    return pair ? decodeURIComponent(pair.slice(pair.indexOf('=') + 1)) : '';
  }
  window.fetch = (input, options = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    const method = (options.method || (typeof input === 'object' && input.method) || 'GET').toUpperCase();
    if (url.origin === location.origin && url.pathname.startsWith('/api/') && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      const headers = new Headers(options.headers || (typeof input === 'object' ? input.headers : undefined));
      const value = csrf(); if (value) headers.set('X-CSRF-Token', value);
      return originalFetch(input, {...options, headers});
    }
    return originalFetch(input, options);
  };
  window.priceSnapLogout = async () => { try { await fetch('/api/auth/logout', {method:'POST'}); } finally { location.href='/'; } };
})();
