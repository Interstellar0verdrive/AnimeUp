(() => {
  const search = document.querySelector('.animeup-header__search');
  const toggle = search?.querySelector('.animeup-search-toggle');
  const input = search?.querySelector('.animeup-search-input');
  const form = search?.querySelector('.animeup-search-form');
  const results = search?.querySelector('.animeup-search-results');
  if (!search || !toggle || !input || !form || !results) return;

  let documents;
  let loadPromise;
  let matches = [];
  const indexUrl = new URL(input.dataset.indexUrl, location.href);
  const siteUrl = new URL('../', indexUrl);

  const loadIndex = () => {
    if (!loadPromise) {
      loadPromise = fetch(indexUrl)
        .then((response) => {
          if (!response.ok) throw new Error(`Search index: ${response.status}`);
          return response.json();
        })
        .then((index) => {
          const parser = new DOMParser();
          documents = index.docs.map((page) => ({
            title: page.title,
            text: parser.parseFromString(page.text || '', 'text/html').body.textContent.replace(/\s+/g, ' ').trim(),
            url: new URL(page.location, siteUrl).href,
          }));
        });
    }
    return loadPromise;
  };

  const render = () => {
    results.replaceChildren();
    matches = [];
    const terms = input.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.length) return;
    if (!documents) {
      results.textContent = 'Searching…';
      return;
    }

    const seen = new Set();
    matches = documents
      .map((page) => {
        const title = page.title.toLocaleLowerCase();
        const text = page.text.toLocaleLowerCase();
        if (!terms.every((term) => title.includes(term) || text.includes(term))) return null;
        const score = terms.reduce((total, term) => total + (title.includes(term) ? 6 : 0) + (text.includes(term) ? 1 : 0), 0);
        return { ...page, score };
      })
      .filter(Boolean)
      .sort((a, b) => b.score - a.score || Number(a.url.includes('#')) - Number(b.url.includes('#')) || a.title.localeCompare(b.title))
      .filter((page) => {
        const key = `${page.url.split('#')[0]}|${page.title}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .slice(0, 8);

    if (!matches.length) {
      results.textContent = 'No matching pages';
      return;
    }

    const list = document.createElement('ul');
    for (const page of matches) {
      const term = terms.find((word) => page.text.toLocaleLowerCase().includes(word));
      const matchAt = term ? page.text.toLocaleLowerCase().indexOf(term) : 0;
      const start = Math.max(0, matchAt - 55);
      const excerpt = page.text.slice(start, start + 150);
      const item = document.createElement('li');
      const link = document.createElement('a');
      const title = document.createElement('strong');
      const snippet = document.createElement('span');
      link.href = page.url;
      title.textContent = page.title;
      snippet.textContent = `${start ? '…' : ''}${excerpt}${page.text.length > start + 150 ? '…' : ''}`;
      link.append(title, snippet);
      item.append(link);
      list.append(item);
    }
    results.append(list);
  };

  const close = () => {
    search.classList.remove('is-open');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-label', 'Open search');
    results.replaceChildren();
  };

  toggle.addEventListener('click', () => {
    if (search.classList.contains('is-open')) {
      close();
      return;
    }
    search.classList.add('is-open');
    toggle.setAttribute('aria-expanded', 'true');
    toggle.setAttribute('aria-label', 'Close search');
    setTimeout(() => input.focus(), 30);
    loadIndex().then(render).catch(() => {
      results.textContent = 'Search is temporarily unavailable';
    });
  });

  input.addEventListener('input', render);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown' && matches.length) {
      event.preventDefault();
      results.querySelector('a')?.focus();
    }
  });
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (matches.length) location.href = matches[0].url;
  });
  results.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const links = [...results.querySelectorAll('a')];
      const current = links.indexOf(document.activeElement);
      const next = current + (event.key === 'ArrowDown' ? 1 : -1);
      (links[next] || input).focus();
    }
  });
  document.addEventListener('click', (event) => {
    if (!search.contains(event.target)) close();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && search.classList.contains('is-open')) {
      close();
      toggle.focus();
    }
  });
})();
