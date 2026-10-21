(() => {
    "use strict";

    const form = document.querySelector("[data-article-editor]");
    if (!form) return;

    const MAX_COVER_BYTES = 5 * 1024 * 1024;
    const COVER_TYPES = ["image/jpeg", "image/png", "image/webp"];
    const WORDS_PER_MINUTE = 200;
    const maxTags = Number(form.dataset.maxTags) || 5;
    const $ = (selector) => form.querySelector(selector);
    const title = $("[name='title']");
    const excerpt = $("[name='excerpt']");
    const content = $("[name='content']");
    const tagsField = $("[name='tags']");
    const cover = $("[data-article-cover]");
    const coverInput = $("[data-article-cover-input]");
    const coverClear = $("[data-article-cover-clear]");
    const coverImage = $("[data-article-cover-image]");
    const coverMeta = $("[data-article-cover-meta]");
    const coverError = $("[data-article-cover-error]");
    const previewImage = $("[data-article-preview-image]");
    let words = 0;
    const isPhone = window.matchMedia("(max-width: 760px)").matches;
    let readyFolded = false;

    const plural = (count, one, few, many) => {
        const tens = count % 100;
        const units = count % 10;
        if (tens > 10 && tens < 20) return many;
        if (units === 1) return one;
        return units > 1 && units < 5 ? few : many;
    };
    const minutes = () => Math.max(words ? 1 : 0, Math.ceil(words / WORDS_PER_MINUTE));

    const updateCounters = () => {
        form.querySelectorAll("[data-article-counter]").forEach((counter) => {
            const field = document.getElementById(counter.dataset.articleCounter);
            if (field) counter.textContent = `${field.value.length} / ${field.maxLength}`;
        });
    };

    const updateReady = () => {
        const category = form.querySelector("[name='category']:checked");
        const checks = {
            title: Boolean(title.value.trim()),
            cover: cover.classList.contains("has-image"),
            excerpt: excerpt.value.trim().length >= 100,
            category: Boolean(category),
            content: words >= 300,
        };
        const done = Object.values(checks).filter(Boolean).length;
        const total = Object.keys(checks).length;
        Object.entries(checks).forEach(([key, ok]) => {
            form.querySelector(`[data-article-check="${key}"]`)?.classList.toggle("is-done", ok);
        });
        const ready = $("[data-article-ready]");
        ready.classList.toggle("is-complete", done === total);
        // A phone shows a finished checklist as one line, once; the capper can unfold it.
        if (isPhone && done === total && !readyFolded) {
            ready.open = false;
            readyFolded = true;
        }
        $("[data-article-ready-count]").textContent = `${done} из ${total}`;
        $("[data-article-ready-title]").textContent = done === total ? "Всё готово к отправке" : "Готовность к отправке";
        $("[data-article-ready-bar]").style.width = `${(done / total) * 100}%`;

        $("[data-article-preview-title]").textContent = title.value.trim() || "Заголовок статьи";
        $("[data-article-preview-excerpt]").textContent = excerpt.value.trim() || "Краткое описание появится здесь";
        $("[data-article-preview-category]").textContent = category?.closest("label")?.textContent.trim() || "Категория";
        $("[data-article-preview-minutes]").textContent = `${Math.max(1, minutes())} мин чтения`;
    };

    const updateWords = (text) => {
        words = text.trim() ? text.trim().split(/\s+/).length : 0;
        $("[data-article-words]").textContent = words;
        $("[data-article-words]").nextSibling.textContent = ` ${plural(words, "слово", "слова", "слов")} · `;
        $("[data-article-minutes]").textContent = words ? `~${minutes()} мин чтения` : "0 мин";
        updateReady();
    };

    // Cover --------------------------------------------------------------------------------
    const showCover = (url, meta) => {
        cover.classList.toggle("has-image", Boolean(url));
        cover.classList.remove("is-invalid");
        coverImage.hidden = !url;
        previewImage.hidden = !url;
        if (url) {
            coverImage.src = url;
            previewImage.src = url;
        }
        coverMeta.hidden = !meta;
        coverMeta.textContent = meta || "";
        updateReady();
    };

    const rejectCover = (message) => {
        coverInput.value = "";
        cover.classList.add("is-invalid");
        cover.closest(".article-editor-field").classList.add("is-invalid");
        $("[data-article-cover-title]").textContent = message;
        coverError.textContent = message;
        coverError.hidden = false;
    };

    const takeCover = (file) => {
        if (!file) return;
        if (!COVER_TYPES.includes(file.type)) {
            rejectCover("Файл не загружен: нужен JPG, PNG или WebP");
            return;
        }
        if (file.size > MAX_COVER_BYTES) {
            rejectCover("Файл не загружен: он больше 5 МБ — сожмите изображение");
            return;
        }
        coverError.hidden = true;
        cover.closest(".article-editor-field").classList.remove("is-invalid");
        coverClear.checked = false;
        const url = URL.createObjectURL(file);
        const probe = new Image();
        probe.onload = () => {
            const size = (file.size / 1024 / 1024).toFixed(1).replace(".", ",");
            showCover(url, `${probe.naturalWidth} × ${probe.naturalHeight} · ${size} МБ`);
        };
        probe.src = url;
    };

    coverInput.addEventListener("change", () => takeCover(coverInput.files[0]));
    $("[data-article-cover-remove]").addEventListener("click", () => {
        coverInput.value = "";
        coverClear.checked = true;
        showCover("", "");
    });
    ["dragenter", "dragover"].forEach((type) => cover.addEventListener(type, (event) => {
        event.preventDefault();
        cover.classList.add("is-dragging");
    }));
    ["dragleave", "drop"].forEach((type) => cover.addEventListener(type, () => cover.classList.remove("is-dragging")));
    cover.addEventListener("drop", (event) => {
        event.preventDefault();
        const file = event.dataTransfer.files[0];
        if (!file) return;
        const transfer = new DataTransfer();
        transfer.items.add(file);
        coverInput.files = transfer.files;
        takeCover(file);
    });

    // Tags ---------------------------------------------------------------------------------
    const tagBox = $("[data-article-tags]");
    const tagInput = $("[data-article-tag-input]");
    const tagNames = () => Array.from(tagBox.querySelectorAll("[data-article-tag]"), (tag) => tag.firstChild.textContent.trim());

    const syncTags = () => {
        const names = tagNames();
        tagsField.value = names.join(", ");
        $("[data-article-tags-count]").textContent = `${names.length} / ${maxTags}`;
        const full = names.length >= maxTags;
        tagInput.hidden = full;
        $("[data-article-tag-add]").hidden = full;
    };

    const addTag = () => {
        const name = tagInput.value.replace(/[,#]/g, " ").replace(/\s+/g, " ").trim().slice(0, 30);
        tagInput.value = "";
        if (!name || tagNames().length >= maxTags) return;
        if (tagNames().some((existing) => existing.toLowerCase() === name.toLowerCase())) return;
        const tag = document.createElement("span");
        tag.className = "article-tag";
        tag.dataset.articleTag = "";
        tag.append(document.createTextNode(name));
        const remove = document.createElement("button");
        remove.type = "button";
        remove.setAttribute("aria-label", "Удалить тег");
        remove.textContent = "×";
        tag.append(remove);
        tagInput.before(tag);
        syncTags();
    };

    tagInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === ",") {
            event.preventDefault();
            addTag();
        } else if (event.key === "Backspace" && !tagInput.value) {
            tagBox.querySelector("[data-article-tag]:last-of-type")?.remove();
            syncTags();
        }
    });
    $("[data-article-tag-add]").addEventListener("click", () => {
        if (tagInput.value.trim()) addTag();
        tagInput.focus();
    });
    tagBox.addEventListener("click", (event) => {
        const remove = event.target.closest("[data-article-tag] button");
        if (!remove) return;
        remove.parentElement.remove();
        syncTags();
    });

    // Text editor --------------------------------------------------------------------------
    const hookEditor = (attempt = 0) => {
        const editor = window.tinymce?.get(content.id);
        if (!editor) {
            updateWords(content.value.replace(/<[^>]*>/g, " "));
            if (attempt < 50) window.setTimeout(() => hookEditor(attempt + 1), 200);
            return;
        }
        const count = () => updateWords(editor.getContent({ format: "text" }));
        editor.on("init input change keyup SetContent Undo Redo", count);
        if (editor.initialized) count();
        $("[data-article-fullscreen]").addEventListener("click", () => editor.execCommand("mceFullScreen"));
    };

    // Phones open with the checklist only; the preview and the rules unfold on demand.
    if (isPhone) {
        form.querySelectorAll("[data-article-collapsible]").forEach((details) => details.removeAttribute("open"));
    }

    [title, excerpt].forEach((field) => field.addEventListener("input", () => {
        updateCounters();
        updateReady();
    }));
    form.addEventListener("change", (event) => {
        if (event.target.name === "category") updateReady();
    });
    // A tag typed but not confirmed is kept on save.
    form.addEventListener("submit", () => {
        if (tagInput.value.trim()) addTag();
    });

    updateCounters();
    syncTags();
    hookEditor();
})();
