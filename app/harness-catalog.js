(function (global) {
  'use strict';
  const STATUS = 'catalogued-not-installed-not-executed';
  const text = (value, max = 600) => typeof value === 'string' ? value.slice(0, max) : '';

  function safeSource(value, commit, path) {
    if (!/^[a-f0-9]{40}$/.test(commit || '') || typeof path !== 'string' || path.length > 1000) return null;
    if (!/^(?:[A-Za-z0-9_.-]+\/)+SKILL\.md$/.test(path) || path.split('/').some(p => p === '.' || p === '..')) return null;
    const expected = 'https://github.com/NousResearch/hermes-agent/blob/' + commit + '/' + path;
    return value === expected ? expected : null;
  }

  function element(document, tag, value, className) {
    const node = document.createElement(tag);
    if (value !== undefined) node.textContent = value;
    if (className) node.className = className;
    return node;
  }

  function skillCard(document, skill) {
    const card = element(document, 'article', undefined, 'card');
    card.append(element(document, 'h3', text(skill.name, 160)), element(document, 'span', 'Catalogued source', 'tag'));
    card.append(element(document, 'p', text(skill.description)), element(document, 'small', text(skill.category, 80)));
    const source = safeSource(skill.source_url, skill.commit, skill.path);
    if (source) {
      const link = element(document, 'a', 'Read pinned upstream source');
      link.href = source; link.target = '_blank'; link.rel = 'noopener noreferrer';
      const paragraph = element(document, 'p'); paragraph.append(link); card.append(paragraph);
    } else card.append(element(document, 'p', 'Source link unavailable; verify the catalogue entry.', 'error'));
    const requirements = element(document, 'details'); requirements.append(element(document, 'summary', 'Requirements and review gaps'));
    const gaps = element(document, 'ul');
    (Array.isArray(skill.dependency_gaps) ? skill.dependency_gaps : []).slice(0, 8).forEach(gap => gaps.append(element(document, 'li', text(gap))));
    requirements.append(gaps);
    const signals = (Array.isArray(skill.dependency_signals) ? skill.dependency_signals : []).slice(0, 32).map(s => text(s, 160));
    if (signals.length) requirements.append(element(document, 'p', 'Dependency hints: ' + signals.join(', ') + '. These are lexical hints, not resolved requirements.'));
    const count = Number.isInteger(skill.support_file_count) ? skill.support_file_count : 0;
    requirements.append(element(document, 'p', count + ' supporting files listed; their contents and local compatibility require review.'));
    requirements.append(element(document, 'p', 'Brain applicability remains unevaluated. A matching source does not authorize installation or execution.'));
    card.append(requirements);
    const provenance = element(document, 'details'); provenance.append(element(document, 'summary', 'Source identity'));
    provenance.append(element(document, 'p', text(skill.path, 1000)), element(document, 'code', 'Commit ' + text(skill.commit, 40)),
      element(document, 'p', 'SHA256 ' + text(skill.sha256, 64)));
    card.append(provenance); return card;
  }

  function checkedResponse(value) {
    if (!value || !/^[a-f0-9]{40}$/.test(value.commit || '') || !Array.isArray(value.skills) || value.skills.length > 32 ||
      !Array.isArray(value.categories) || value.categories.length > 64 || !Number.isInteger(value.skills_total) || !Number.isInteger(value.matches_total)) {
      throw new Error('Malformed catalogue response.');
    }
    if (value.matches_total < value.skills.length || value.skills_total < value.matches_total || value.skills_total < 0) throw new Error('Conflicting catalogue counts.');
    value.categories.forEach(item => {if (!item || typeof item.name !== 'string' || item.name.length > 80 || !Number.isInteger(item.count) || item.count < 0) throw new Error('Malformed category metadata.');});
    value.skills.forEach(skill => {
      if (!skill || skill.adoption_status !== STATUS || skill.fit_validation !== 'not-evaluated' || skill.commit !== value.commit ||
        !/^[a-f0-9]{64}$/.test(skill.sha256 || '') || typeof skill.name !== 'string' || typeof skill.description !== 'string' ||
        typeof skill.category !== 'string' || typeof skill.path !== 'string') throw new Error('Unsupported catalogue status or source identity.');
    });
    return value;
  }

  function mount(document, fetcher) {
    const form = document.getElementById('catalog-search'), query = document.getElementById('catalog-query');
    const category = document.getElementById('catalog-category'), submit = document.getElementById('catalog-submit');
    const clear = document.getElementById('catalog-clear'), status = document.getElementById('catalog-status');
    const pin = document.getElementById('catalog-pin'), results = document.getElementById('catalog-results');
    let generation = 0;
    async function load() {
      const ticket = ++generation; submit.disabled = true; status.className = 'status';
      status.textContent = 'Loading the source catalogue…'; pin.textContent = ''; results.replaceChildren();
      const params = new URLSearchParams({query: query.value.slice(0, 1000), category: category.value, limit: '32'});
      try {
        const response = await fetcher('/api/harness-catalog?' + params.toString(), {method: 'GET', headers: {Accept: 'application/json'}, cache: 'no-store'});
        if (!response.ok) throw new Error('Catalogue unavailable.');
        const raw = await response.text();
        if (raw.length > 512 * 1024) throw new Error('Catalogue response exceeds the display limit.');
        const catalog = checkedResponse(JSON.parse(raw)); if (ticket !== generation) return;
        const selected = category.value, options = [element(document, 'option', 'All categories')]; options[0].value = '';
        catalog.categories.forEach(item => {const option = element(document, 'option', text(item.name, 80) + ' (' + Number(item.count) + ')'); option.value = text(item.name, 80); options.push(option);});
        category.replaceChildren(...options); category.value = selected;
        results.replaceChildren(...catalog.skills.map(skill => skillCard(document, skill)));
        status.textContent = catalog.matches_total ? 'Showing ' + catalog.skills.length + ' of ' + catalog.matches_total + ' matching sources · ' + catalog.skills_total + ' in the pinned catalogue.' : 'No sources match these filters. Try a broader term or clear the filters.';
        if (catalog.truncated) status.textContent += ' Refine the search or choose a category to see more.';
        pin.textContent = 'Source commit ' + catalog.commit.slice(0, 12) + ' · captured ' + text(catalog.captured_at, 80) + '. Catalogue capture does not verify local use.';
      } catch (error) {
        if (ticket !== generation) return;
        status.className = 'status error'; status.textContent = 'The catalogue could not be loaded. Search again to retry; local project records are preserved.';
      } finally { if (ticket === generation) submit.disabled = false; }
    }
    form.addEventListener('submit', event => {event.preventDefault(); return load();});
    category.addEventListener('change', load);
    clear.addEventListener('click', () => {query.value = ''; category.value = ''; return load();});
    load(); return {load};
  }

  const api = {safeSource, skillCard, checkedResponse, mount};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else {global.CompanyBrainHarnessCatalog = api; mount(global.document, global.fetch.bind(global));}
})(typeof window === 'undefined' ? globalThis : window);
