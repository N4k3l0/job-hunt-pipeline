// Job Hunt extension: fills in a Greenhouse, Lever or Ashby application
// form with the answers the user approved in the app.
//
// Runs in the page's own JavaScript world, not the extension's, because
// Greenhouse's dropdowns only take a choice through their React component.
// form-bridge.js hands over the answers with window.postMessage.
// Nothing here presses Submit: the user checks the form and sends it.

(() => {
  if (window.__jobHuntFiller) return;
  window.__jobHuntFiller = true;

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const norm = (text) => String(text ?? "").replace(/\s+/g, " ").replace(/\*$/, "").trim().toLowerCase();
  const isEmpty = (value) =>
    value === null || value === undefined || value === "" || (Array.isArray(value) && value.length === 0);

  const NOT_FOUND = "Couldn't find this question on the page. Answer it on the form.";
  const PICK = "Pick your answer on the form.";

  async function waitFor(find, timeoutMs) {
    const end = Date.now() + timeoutMs;
    for (;;) {
      const found = find();
      if (found || Date.now() > end) return found || null;
      await sleep(250);
    }
  }

  // ─── Setting values the way the page's own code expects ────────────────

  function setText(element, value) {
    const proto = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(element, String(value));
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    element.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
  }

  function setChecked(input, checked) {
    if (input.checked !== checked) input.click();
  }

  function attachFile(input, resume) {
    const bytes = Uint8Array.from(atob(resume.base64), (c) => c.charCodeAt(0));
    const transfer = new DataTransfer();
    transfer.items.add(new File([bytes], resume.name, { type: resume.type }));
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  // The option labels the answer stands for (answers hold option values).
  function wantedLabels(field) {
    const values = Array.isArray(field.value) ? field.value : [field.value];
    return values.map((value) => {
      const option = (field.options || []).find((o) => String(o.value) === String(value));
      return norm(option ? option.label : value);
    });
  }

  function formatDate(input, value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value));
    if (!match || input.type === "date") return String(value);
    return `${match[2]}/${match[3]}/${match[1]}`;
  }

  // Type into a search-as-you-type box and pick the closest suggestion.
  async function pickSuggestion(input, text) {
    setText(input, text);
    const first = await waitFor(() => document.querySelector("[role=option]"), 5000);
    if (!first) return false;
    const options = [...document.querySelectorAll("[role=option]")];
    const exact = options.find((o) => norm(o.textContent) === norm(text));
    const starts = options.find((o) => norm(o.textContent).startsWith(norm(text)));
    (exact || starts || first).click();
    await sleep(300);
    return true;
  }

  // Greenhouse dropdowns are react-select components. Their choice can only
  // be set through the component, found from the input's React fiber.
  function reactSelect(input) {
    const key = Object.keys(input).find((k) => k.startsWith("__reactFiber$"));
    let fiber = key ? input[key] : null;
    for (let depth = 0; fiber && depth < 40; depth++, fiber = fiber.return) {
      if (fiber.stateNode && typeof fiber.stateNode.selectOption === "function") return fiber.stateNode;
    }
    return null;
  }

  function chooseInReactSelect(input, field) {
    const select = reactSelect(input);
    if (!select) return false;
    const options = (select.props.options || []).flatMap((o) => (Array.isArray(o.options) ? o.options : [o]));
    const values = (Array.isArray(field.value) ? field.value : [field.value]).map(String);
    const labels = wantedLabels(field);
    const picks = labels.map(
      (label, i) => options.find((o) => norm(o.label) === label) || options.find((o) => String(o.value) === values[i]),
    );
    if (!picks.length || picks.some((p) => !p)) return false;
    const chosen = [].concat(select.props.value || []);
    for (const option of picks) {
      if (select.props.isMulti && chosen.some((c) => c.value === option.value)) continue;
      select.selectOption(option);
    }
    return true;
  }

  // ─── One adapter per hiring system ─────────────────────────────────────

  const result = (field, status, element, note) => ({ field, status, element, note });

  const hasReact = (element) => Object.keys(element).some((k) => k.startsWith("__reactProps$"));

  const greenhouse = {
    // Greenhouse's page is rendered on the server and then taken over by
    // React. Touching it before that finishes makes React redraw the page,
    // which drops the panel and the attached resume.
    ready: () => {
      const form = document.querySelector("#application-form, #application_form");
      const input = form && form.querySelector("input");
      return input && hasReact(input) ? form : null;
    },
    fileInput: (field) => {
      const input = document.getElementById(field.key);
      return input && input.type === "file" ? input : null;
    },
    fileArea: (field, input) => {
      const label = document.getElementById(`upload-label-${field.key}`);
      return label ? label.parentElement : input.parentElement;
    },
    box: (element) =>
      element.closest(".field-wrapper, .select__container, .file-upload, .checkbox, fieldset") || element.parentElement,
    async fill(field) {
      const element = document.getElementById(field.key);
      if (field.type === "boolean") {
        const box =
          element && element.type === "checkbox"
            ? element
            : document.querySelector(`input[type=checkbox][name*="${field.key.split("_").pop()}"]`);
        if (!box) return result(field, "todo", null, "Tick this box on the form if you agree.");
        setChecked(box, Boolean(field.value));
        return result(field, "filled", box);
      }
      if (!element) {
        const boxes = [...document.querySelectorAll(`input[type=checkbox][name^="${field.key}"], input[type=checkbox][id^="${field.key}"]`)];
        if (boxes.length && field.options) {
          const labels = wantedLabels(field);
          const matched = boxes.filter((b) => labels.includes(norm(b.labels && b.labels[0] ? b.labels[0].textContent : b.value)));
          matched.forEach((b) => setChecked(b, true));
          if (matched.length === labels.length) return result(field, "filled", boxes[0]);
        }
        return result(field, "todo", null, field.type === "location" ? "Type your location on the form and pick it from the list." : NOT_FOUND);
      }
      if (element.getAttribute("role") === "combobox") {
        return chooseInReactSelect(element, field) ? result(field, "filled", element) : result(field, "todo", element, PICK);
      }
      if (element.type === "checkbox") {
        setChecked(element, Boolean(field.value));
        return result(field, "filled", element);
      }
      setText(element, field.type === "date" ? formatDate(element, field.value) : field.value);
      return result(field, "filled", element);
    },
  };

  const lever = {
    ready: () => document.querySelector("#application-form"),
    fileInput: (field) =>
      [...document.querySelectorAll("#application-form input[type=file]")].find((input) => input.name === field.key) || null,
    fileArea: (field, input) => input.closest(".application-question, li") || input.parentElement,
    box: (element) => element.closest(".application-question, li") || element.parentElement,
    async fill(field) {
      const form = document.querySelector("#application-form");
      const named = [...form.querySelectorAll("input, select, textarea")].filter((e) => e.name === field.key);
      const first = named[0];
      if (!first) return result(field, "todo", null, NOT_FOUND);
      if (first.type === "radio" || first.type === "checkbox") {
        if (field.type === "boolean") {
          setChecked(first, Boolean(field.value));
          return result(field, "filled", first);
        }
        const labels = wantedLabels(field);
        let all = true;
        for (const label of labels) {
          const input = named.find((i) => norm(i.value) === label);
          if (input) setChecked(input, true);
          else all = false;
        }
        return all ? result(field, "filled", first) : result(field, "todo", first, PICK);
      }
      if (first.tagName === "SELECT") {
        const labels = wantedLabels(field);
        const option = [...first.options].find((o) => labels.includes(norm(o.value)) || labels.includes(norm(o.textContent)));
        if (!option) return result(field, "todo", first, PICK);
        first.value = option.value;
        first.dispatchEvent(new Event("change", { bubbles: true }));
        return result(field, "filled", first);
      }
      if (field.type === "location") {
        setText(first, field.value);
        const suggestion = await waitFor(() => document.querySelector(".dropdown-location"), 4000);
        if (suggestion) {
          suggestion.click();
          return result(field, "filled", first);
        }
        return result(field, "check", first, "Check your location: pick it from the list if one appears.");
      }
      setText(first, field.type === "date" ? formatDate(first, field.value) : field.value);
      return result(field, "filled", first);
    },
  };

  const ashby = {
    ready: () => document.querySelector("[data-field-path]"),
    entry: (field) => {
      const path = field.key.replace(/^survey:[^:]*:/, "");
      return [...document.querySelectorAll("[data-field-path]")].find((e) => e.dataset.fieldPath === path) || null;
    },
    fileInput(field) {
      const entry = this.entry(field);
      return entry ? entry.querySelector("input[type=file]") : null;
    },
    fileArea: (field, input) => input.closest("[data-field-path]") || input.parentElement,
    box: (element) => element.closest("[data-field-path]") || element.parentElement,
    async fill(field) {
      const entry = this.entry(field);
      if (!entry) return result(field, "todo", null, NOT_FOUND);

      if (field.type === "boolean") {
        const button = entry.querySelector(`button[data-option="${field.value ? "yes" : "no"}"]`);
        if (button) {
          if (button.getAttribute("aria-pressed") !== "true") button.click();
          return result(field, "filled", entry);
        }
        const box = entry.querySelector("input[type=checkbox]");
        if (!box) return result(field, "todo", entry, PICK);
        setChecked(box, Boolean(field.value));
        return result(field, "filled", entry);
      }

      if (field.type === "select" || field.type === "multiselect") {
        const labels = wantedLabels(field);
        const choices = [...entry.querySelectorAll("label[for]")]
          .map((label) => ({ label: norm(label.textContent), input: document.getElementById(label.htmlFor) }))
          .filter((c) => c.input && (c.input.type === "radio" || c.input.type === "checkbox"));
        if (choices.length) {
          const picks = labels.map((label) => choices.find((c) => c.label === label));
          picks.filter(Boolean).forEach((c) => setChecked(c.input, true));
          return picks.every(Boolean) ? result(field, "filled", entry) : result(field, "todo", entry, PICK);
        }
        const buttons = [...entry.querySelectorAll("button")];
        if (buttons.length) {
          const picks = labels.map((label) => buttons.find((b) => norm(b.textContent) === label));
          picks.filter(Boolean).forEach((b) => b.getAttribute("aria-pressed") !== "true" && b.click());
          if (picks.every(Boolean)) return result(field, "filled", entry);
        }
        const combobox = entry.querySelector("input[role=combobox]");
        if (combobox && labels.length === 1) {
          const option = (field.options || []).find((o) => norm(o.label) === labels[0]);
          if (await pickSuggestion(combobox, option ? option.label : field.value)) return result(field, "filled", entry);
        }
        return result(field, "todo", entry, PICK);
      }

      if (field.type === "location") {
        const input = entry.querySelector("input");
        if (input && (await pickSuggestion(input, field.value))) {
          return result(field, "check", entry, "Check the location it picked.");
        }
        return result(field, "todo", entry, "Type your location and pick it from the list.");
      }

      const input = entry.querySelector("textarea, input:not([type=file]):not([type=checkbox]):not([type=radio])");
      if (!input) return result(field, "todo", entry, NOT_FOUND);
      if (field.type === "date") {
        setText(input, formatDate(input, field.value));
        return result(field, "check", entry, "Check the date.");
      }
      setText(input, field.value);
      return result(field, "filled", entry);
    },
  };

  const ADAPTERS = { greenhouse, lever, ashby };

  // ─── Filling the whole form ────────────────────────────────────────────

  let current = null;
  let running = false;

  async function fillFile(adapter, field, resume) {
    const hasAnswer = !isEmpty(field.value);
    if (field.kind !== "resume" || !hasAnswer) {
      return field.required ? result(field, "todo", null, "Attach this file on the form.") : null;
    }
    if (!resume) return result(field, "todo", null, "Attach your resume on the form.");
    // The upload can fail while the page is still setting up (Greenhouse):
    // check the file's name shows, and try again if it doesn't.
    let area = null;
    for (let attempt = 0; attempt < 3; attempt++) {
      const input = await waitFor(() => adapter.fileInput(field), 4000);
      if (!input) break;
      area = adapter.fileArea(field, input);
      attachFile(input, resume);
      if (await waitFor(() => area && norm(area.innerText).includes(norm(resume.name)), 5000)) {
        return result(field, "filled", null);
      }
      await sleep(2000);
    }
    return result(field, "todo", area, "Attach your resume on the form.");
  }

  async function fill(application, resume) {
    if (running) return;
    running = true;
    current = { application, resume };
    clearHighlights();
    try {
      const adapter = ADAPTERS[application.ats];
      if (!adapter) return;
      const form = await waitFor(adapter.ready, 20000);
      if (!form) {
        showPanel({
          title: "Couldn't find the application form",
          lines: ["If the posting has closed, there's nothing to fill in."],
        });
        return;
      }
      await sleep(500);
      showPanel({ title: "Filling in your answers…" });

      const results = [];
      // The resume goes first: Lever and Ashby read it and fill in some
      // boxes themselves, which the approved answers then replace.
      for (const field of application.fields.filter((f) => f.type === "file")) {
        const outcome = await fillFile(adapter, field, resume);
        if (outcome) results.push(outcome);
      }
      if (results.some((r) => r.status === "filled")) await sleep(2500);

      for (const field of application.fields.filter((f) => f.type !== "file")) {
        if (isEmpty(field.value)) {
          if (field.required) results.push(result(field, "todo", null, "Answer this on the form."));
          continue;
        }
        let outcome;
        try {
          outcome = await adapter.fill(field);
        } catch {
          outcome = result(field, "todo", null, "Couldn't fill this in. Answer it on the form.");
        }
        // Optional survey questions that only show up after another answer
        // aren't worth bothering the user about.
        if (outcome.status === "todo" && field.group === "voluntary" && !field.required) continue;
        results.push(outcome);
      }
      showResults(adapter, results);
      // Greenhouse puts the form below the job description.
      if (form.getBoundingClientRect().top > window.innerHeight) form.scrollIntoView({ behavior: "smooth", block: "start" });
    } finally {
      running = false;
    }
  }

  // ─── The panel on the form page ────────────────────────────────────────

  let host = null;
  let shadow = null;
  const highlighted = new Set();

  function clearHighlights() {
    highlighted.forEach((element) => {
      element.style.outline = "";
      element.style.outlineOffset = "";
    });
    highlighted.clear();
  }

  function highlight(element) {
    element.style.outline = "2px solid #d97706";
    element.style.outlineOffset = "4px";
    highlighted.add(element);
  }

  const STYLE = `
    :host { all: initial; }
    .panel { position: fixed; right: 16px; bottom: 16px; z-index: 2147483647; width: min(340px, calc(100vw - 32px));
      max-height: calc(100vh - 32px); overflow: auto; box-sizing: border-box; padding: 16px; border-radius: 12px;
      background: #ffffff; color: #1a1a1a; border: 1px solid #e5e5e5; box-shadow: 0 12px 32px rgba(0,0,0,.18);
      font: 14px/1.45 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }
    .top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
    .brand { font: 700 11px/1 ui-monospace, Menlo, monospace; letter-spacing: .08em; color: #1f9d7a; }
    .close { border: 0; background: none; font-size: 18px; line-height: 1; cursor: pointer; color: #777; padding: 2px 4px; }
    h2 { font-size: 16px; margin: 4px 0 6px; }
    p { margin: 6px 0; color: #444; }
    ul { list-style: none; padding: 0; margin: 8px 0; }
    li button { width: 100%; text-align: left; border: 1px solid #f3d9a4; background: #fffbeb; border-radius: 8px;
      padding: 8px 10px; margin: 0 0 6px; cursor: pointer; font: inherit; color: inherit; }
    li strong { display: block; font-size: 13px; }
    li span { display: block; font-size: 12px; color: #6b5a2b; }
    .actions { display: flex; gap: 8px; margin-top: 10px; }
    .action { border: 1px solid #d4d4d4; background: #fff; border-radius: 8px; padding: 7px 12px; font: inherit;
      font-size: 13px; cursor: pointer; color: inherit; }
    .small { font-size: 12px; color: #777; }
  `;

  function showPanel({ title, lines = [], items = [], actions = [], footer = null }) {
    if (!host) {
      host = document.createElement("job-hunt-panel");
      shadow = host.attachShadow({ mode: "closed" });
      // Put the panel back if the page redraws itself and drops it.
      const keepShown = setInterval(() => {
        if (!host) clearInterval(keepShown);
        else if (!host.isConnected) document.documentElement.appendChild(host);
      }, 1000);
    }
    if (!host.isConnected) document.documentElement.appendChild(host);
    shadow.innerHTML = "";
    const style = document.createElement("style");
    style.textContent = STYLE;
    const panel = document.createElement("div");
    panel.className = "panel";
    panel.setAttribute("role", "status");

    const top = document.createElement("div");
    top.className = "top";
    const brand = document.createElement("span");
    brand.className = "brand";
    brand.textContent = "JOB HUNT";
    const close = document.createElement("button");
    close.className = "close";
    close.setAttribute("aria-label", "Close");
    close.textContent = "×";
    close.onclick = () => {
      host.remove();
      host = null;
    };
    top.append(brand, close);

    const heading = document.createElement("h2");
    heading.textContent = title;
    panel.append(top, heading);

    for (const line of lines) {
      const p = document.createElement("p");
      p.textContent = line;
      panel.append(p);
    }
    if (items.length) {
      const list = document.createElement("ul");
      for (const item of items) {
        const li = document.createElement("li");
        const button = document.createElement("button");
        const label = document.createElement("strong");
        label.textContent = item.label;
        const note = document.createElement("span");
        note.textContent = item.note;
        button.append(label, note);
        button.onclick = () => {
          if (!item.element) return;
          item.element.scrollIntoView({ behavior: "smooth", block: "center" });
          const focusable = item.element.matches("input, textarea, select")
            ? item.element
            : item.element.querySelector("input, textarea, select, button");
          if (focusable) focusable.focus({ preventScroll: true });
        };
        li.append(button);
        list.append(li);
      }
      panel.append(list);
    }
    if (actions.length) {
      const row = document.createElement("div");
      row.className = "actions";
      for (const action of actions) {
        const button = document.createElement("button");
        button.className = "action";
        button.textContent = action.label;
        button.onclick = action.onClick;
        row.append(button);
      }
      panel.append(row);
    }
    if (footer) {
      const p = document.createElement("p");
      p.className = "small";
      p.textContent = footer;
      panel.append(p);
    }
    shadow.append(style, panel);
  }

  function showResults(adapter, results) {
    const filled = results.filter((r) => r.status !== "todo").length;
    const attention = results.filter((r) => r.status !== "filled");
    const items = attention.map((r) => {
      const element = r.element ? adapter.box(r.element) : null;
      if (element) highlight(element);
      return { label: r.field.label, note: r.note, element };
    });
    showPanel({
      title: `Filled in ${filled} ${filled === 1 ? "answer" : "answers"}`,
      lines: attention.length
        ? ["Before you press Submit, look at these:"]
        : ["Everything's filled in. Look it over, then press Submit on the form."],
      items,
      actions: [{ label: "Fill in again", onClick: () => current && fill(current.application, current.resume) }],
      footer: "Job Hunt never presses Submit. If the form asks you to prove you're human, do that too.",
    });
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window || !event.data || event.data.jobHunt !== "to-page") return;
    const { type, application, resume } = event.data;
    if (type === "hello") {
      window.postMessage({ jobHunt: "filler-ready" }, location.origin);
    } else if (type === "fill" && application) {
      fill(application, resume);
    } else if (type === "sent") {
      clearHighlights();
      showPanel({ title: "Sent", lines: ["Job Hunt marked this job as applied."] });
    }
  });
  window.postMessage({ jobHunt: "filler-ready" }, location.origin);
})();
