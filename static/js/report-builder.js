(function () {
  const dialog = document.querySelector('[data-report-dialog]');
  const openButton = document.querySelector('[data-report-open]');
  const main = document.querySelector('main[data-report-root], main.content, main');
  if (!dialog || !openButton || !main) return;

  const sectionList = dialog.querySelector('[data-report-sections]');
  const titleField = dialog.querySelector('[data-report-title]');
  const dateField = dialog.querySelector('[data-report-date]');
  const printButton = dialog.querySelector('[data-report-print]');
  const summary = dialog.querySelector('[data-report-summary]');
  const selectionTools = dialog.querySelector('[data-report-selection-tools]');
  const selectAllButton = dialog.querySelector('[data-report-select-all]');
  const clearAllButton = dialog.querySelector('[data-report-clear-all]');
  const reportLogo = dialog.dataset.reportLogo;
  const reportOrganization = dialog.dataset.reportOrganization || '';
  const reportRole = dialog.dataset.reportRole || '';
  const reportArea = dialog.dataset.reportArea || '';
  const reportSource = [reportOrganization, reportRole, reportArea].filter(Boolean).join(' · ');
  const scopeInputs = [...dialog.querySelectorAll('input[name="report-scope"]')];
  let sections = [];

  const labelFor = (node, index) => {
    if (node.dataset.reportLabel) return node.dataset.reportLabel;
    const heading = node.querySelector('h1, h2, h3');
    return heading ? heading.textContent.trim() : `Page section ${index + 1}`;
  };

  const discoverSections = () => {
    const explicit = [...main.querySelectorAll('[data-report-section]')];
    const candidates = explicit.length
      ? explicit
      : [...main.children].filter((node) => !['SCRIPT', 'STYLE'].includes(node.tagName));
    sections = candidates.map((node, index) => ({node, label: labelFor(node, index)}));
  };

  const renderSectionChoices = () => {
    sectionList.replaceChildren();
    const heading = document.createElement('p');
    heading.className = 'report-sections-heading';
    heading.textContent = 'Available sections';
    sectionList.appendChild(heading);
    sections.forEach((section, index) => {
      const label = document.createElement('label');
      label.className = 'report-section-option';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = true;
      checkbox.dataset.reportSectionChoice = String(index);
      const text = document.createElement('span');
      text.textContent = section.label;
      label.append(checkbox, text);
      sectionList.appendChild(label);
    });
    updateChoiceState();
  };

  const updateChoiceState = () => {
    const fullPage = dialog.querySelector('input[name="report-scope"]:checked')?.value === 'full';
    const choices = [...sectionList.querySelectorAll('[data-report-section-choice]')];
    choices.forEach((checkbox) => {
      checkbox.disabled = fullPage;
      checkbox.closest('.report-section-option').classList.toggle('is-disabled', fullPage);
    });
    if (selectionTools) selectionTools.hidden = fullPage;
    if (summary) {
      const count = fullPage ? sections.length : choices.filter((checkbox) => checkbox.checked).length;
      summary.textContent = fullPage
        ? `${count} sections included in the full page report.`
        : `${count} of ${sections.length} pages or sections selected.`;
    }
    if (printButton) printButton.disabled = !fullPage && !choices.some((checkbox) => checkbox.checked);
  };

  const closeDialog = () => {
    if (typeof dialog.close === 'function') dialog.close();
    dialog.hidden = true;
  };

  const openDialog = () => {
    discoverSections();
    renderSectionChoices();
    const pageTitle = main.querySelector('h1');
    const pageLabel = pageTitle ? pageTitle.textContent.trim() : document.title.replace(/ · Rapid Response$/, '');
    const defaultTitle = reportRole
      ? [`${reportRole} report`, reportOrganization].filter(Boolean).join(' — ')
      : [reportOrganization, pageLabel].filter(Boolean).join(' — ');
    titleField.value = defaultTitle || 'Rapid Response report';
    dateField.value = '';
    dialog.hidden = false;
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
  };

  const cloneForPrint = (node, dateValue) => {
    const sourceCanvases = [...node.querySelectorAll('canvas')];
    const clone = node.cloneNode(true);
    clone.querySelectorAll('script, form, button, input, select, textarea, .official-chat-widget, .map-dive-modal, .map-journey-hint, .leaflet-control-container').forEach((item) => item.remove());
    clone.querySelectorAll('canvas').forEach((canvas, index) => {
      try {
        const sourceCanvas = sourceCanvases[index];
        if (!sourceCanvas || !sourceCanvas.width || !sourceCanvas.height) throw new Error('Chart canvas is not ready');
        const image = document.createElement('img');
        image.className = 'report-chart-image';
        image.alt = canvas.getAttribute('aria-label') || 'Chart';
        image.width = sourceCanvas.width;
        image.height = sourceCanvas.height;
        image.src = sourceCanvas.toDataURL('image/png');
        canvas.replaceWith(image);
      } catch (error) {
        const notice = document.createElement('p');
        notice.className = 'report-chart-unavailable';
        notice.textContent = 'Chart image was not available at export time.';
        canvas.replaceWith(notice);
      }
    });
    if (dateValue) {
      const datedItems = [...clone.querySelectorAll('[data-report-date]')];
      const matchingItems = datedItems.filter((item) => item.dataset.reportDate === dateValue);
      datedItems.forEach((item) => {
        if (item.dataset.reportDate !== dateValue) item.remove();
      });
      if (datedItems.length && !matchingItems.length) {
        const empty = document.createElement('p');
        empty.className = 'report-no-results';
        empty.textContent = `No case entries were recorded on ${dateValue}.`;
        clone.appendChild(empty);
      }
    }
    return clone;
  };

  const formatDate = (value) => {
    const date = new Date(`${value}T00:00:00`);
    return Number.isNaN(date.getTime())
      ? value
      : date.toLocaleDateString(undefined, {day: 'numeric', month: 'long', year: 'numeric'});
  };

  const describePeriod = () => {
    if (dateField.value) return `the day of ${formatDate(dateField.value)}`;
    const selectedPeriod = main.querySelector('[data-report-period]')?.dataset.reportPeriod;
    if (selectedPeriod === 'month') return 'the selected month';
    if (selectedPeriod === 'year') return 'the selected year';
    const activePeriod = main.querySelector('.area-period-switch a.active')?.textContent.trim();
    if (!activePeriod) return 'the selected reporting period';
    const normalized = activePeriod.toLowerCase();
    const periodLabel = normalized.match(/^([0-9]+)\s+days?$/)
      ? normalized.replace(' ', '-')
      : normalized;
    return `the selected ${periodLabel} period`;
  };

  const describeScope = (fullPage, selected) => {
    if (fullPage) return 'the complete dashboard view';
    const labels = selected.map((section) => section.label);
    if (labels.length === 1) return labels[0];
    if (labels.length === 2) return `${labels[0]} and ${labels[1]}`;
    return `${labels.slice(0, -1).join(', ')}, and ${labels[labels.length - 1]}`;
  };

  const printReport = () => {
    const fullPage = dialog.querySelector('input[name="report-scope"]:checked')?.value === 'full';
    const selected = fullPage
      ? sections
      : sections.filter((section, index) => sectionList.querySelector(`[data-report-section-choice="${index}"]`)?.checked);
    if (!selected.length) {
      window.alert('Select at least one report section.');
      return;
    }
    const surface = document.createElement('article');
    surface.className = 'report-print-surface content content-shell';
    if (reportLogo) {
      const watermark = document.createElement('img');
      watermark.className = 'report-print-watermark';
      watermark.src = reportLogo;
      watermark.alt = '';
      watermark.setAttribute('aria-hidden', 'true');
      surface.appendChild(watermark);
    }
    const header = document.createElement('header');
    header.className = 'report-print-header';
    if (reportLogo) {
      const logo = document.createElement('img');
      logo.className = 'report-print-logo';
      logo.src = reportLogo;
      logo.alt = 'Rapid Response Emergency';
      header.appendChild(logo);
    }
    const kicker = document.createElement('span');
    kicker.className = 'report-print-kicker';
    kicker.textContent = reportRole ? `${reportRole} · Official operations report` : 'Rapid Response · Official operations report';
    const source = document.createElement('p');
    source.className = 'report-print-source';
    source.textContent = reportSource ? `Prepared by ${reportSource}` : 'Prepared by the Rapid Response operations network';
    const title = document.createElement('h1');
    const reportTitle = titleField.value.trim() || 'Rapid Response report';
    title.textContent = reportTitle;
    const description = document.createElement('p');
    description.className = 'report-print-description';
    description.textContent = `This is an official ${reportSource ? `report from ${reportSource}` : 'Rapid Response report'}, covering ${describeScope(fullPage, selected)} for ${describePeriod()}. It presents the available incident records, operational indicators, maps, and visual analysis captured at the time of export.`;
    const metadata = document.createElement('p');
    metadata.className = 'report-print-metadata';
    metadata.textContent = `Generated ${new Date().toLocaleString()}${dateField.value ? ` · Day filter: ${dateField.value}` : ''}`;
    header.append(kicker, source, title, description, metadata);
    surface.appendChild(header);
    if (fullPage) {
      const pageContent = cloneForPrint(main, dateField.value);
      pageContent.className = 'report-full-page-content';
      surface.appendChild(pageContent);
    } else {
      selected.forEach((section) => {
        const wrapper = document.createElement('section');
        wrapper.className = 'report-print-section';
        const clonedSection = cloneForPrint(section.node, dateField.value);
        const hasOwnHeading = [...clonedSection.children].some((child) => child.matches('.panel-heading, h1, h2, h3'));
        if (!hasOwnHeading) {
          const heading = document.createElement('h2');
          heading.textContent = section.label;
          wrapper.appendChild(heading);
        }
        wrapper.appendChild(clonedSection);
        surface.appendChild(wrapper);
      });
    }
    const footer = document.createElement('footer');
    footer.className = 'report-print-footer';
    footer.textContent = reportSource ? `Rapid Response · ${reportSource} · Internal operations report` : 'Rapid Response · Internal operations report';
    surface.appendChild(footer);
    document.body.appendChild(surface);
    document.body.classList.add('is-printing-report');
    closeDialog();
    const cleanup = () => {
      surface.remove();
      document.body.classList.remove('is-printing-report');
      window.removeEventListener('afterprint', cleanup);
    };
    window.addEventListener('afterprint', cleanup);
    window.setTimeout(() => window.print(), 100);
    window.setTimeout(cleanup, 120000);
  };

  openButton.addEventListener('click', openDialog);
  dialog.querySelectorAll('[data-report-close]').forEach((button) => button.addEventListener('click', closeDialog));
  dialog.addEventListener('click', (event) => { if (event.target === dialog) closeDialog(); });
  scopeInputs.forEach((input) => input.addEventListener('change', updateChoiceState));
  sectionList.addEventListener('change', updateChoiceState);
  selectAllButton?.addEventListener('click', () => {
    sectionList.querySelectorAll('[data-report-section-choice]').forEach((checkbox) => { checkbox.checked = true; });
    updateChoiceState();
  });
  clearAllButton?.addEventListener('click', () => {
    sectionList.querySelectorAll('[data-report-section-choice]').forEach((checkbox) => { checkbox.checked = false; });
    updateChoiceState();
  });
  printButton.addEventListener('click', printReport);
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && dialog.open) closeDialog(); });
}());
