(() => {
    const root = document.querySelector("[data-prediction-comments]");
    if (!root) return;

    const list = root.querySelector("[data-comments-list]");
    const form = root.querySelector("[data-comment-form]");
    const textarea = root.querySelector("[data-comment-text]");
    const submitButton = root.querySelector("[data-comment-submit]");
    const lengthNode = root.querySelector("[data-comment-length]");
    const feedback = root.querySelector("[data-comment-feedback]");
    const loadError = root.querySelector("[data-comments-load-error]");
    const moreButton = root.querySelector("[data-comments-more]");
    const totalNode = root.querySelector("[data-comments-total]");
    const commentsUrl = root.dataset.commentsUrl || "";
    const deleteUrlTemplate = root.dataset.deleteUrlTemplate || "";
    const predictionId = root.dataset.predictionId || "";
    const LATEST_PAGE = 999999999;

    let previousPage = Number.parseInt(root.dataset.previousPage || "", 10) || null;
    let loading = false;
    let submitting = false;

    const getCookie = (name) => {
        const prefix = `${name}=`;
        return document.cookie
            .split(";")
            .map((item) => item.trim())
            .find((item) => item.startsWith(prefix))
            ?.slice(prefix.length) || "";
    };

    const setListLoading = (active) => {
        if (!list) return;
        if (active) {
            window.CappersSkeleton?.loading(list);
            list.classList.add("is-skeleton-loading");
            list.setAttribute("aria-busy", "true");
            return;
        }
        window.CappersSkeleton?.ready(list);
        list.classList.remove("is-skeleton-loading");
        list.setAttribute("aria-busy", "false");
    };

    const setFeedback = (message = "", kind = "") => {
        if (!feedback) return;
        feedback.textContent = message;
        feedback.hidden = !message;
        feedback.classList.toggle("is-error", kind === "error");
        feedback.classList.toggle("is-rate-limit", kind === "rate");
        feedback.classList.toggle("is-success", kind === "success");
    };

    const setLoadError = (message = "") => {
        if (!loadError) return;
        loadError.textContent = message;
        loadError.hidden = !message;
    };

    const updateCounters = (count) => {
        const parsed = Number.parseInt(count, 10);
        if (!Number.isFinite(parsed)) return;
        const safeCount = Math.max(0, parsed);

        if (totalNode) totalNode.textContent = String(safeCount);

        document.querySelectorAll("[data-comment-count]").forEach((node) => {
            if (node.dataset.commentCount !== predictionId) return;
            node.textContent = String(safeCount);
            const link = node.closest(".prediction-comment-metric");
            if (link) {
                link.setAttribute(
                    "aria-label",
                    `Открыть прогноз и комментарии, комментариев: ${safeCount}`,
                );
            }
        });
    };

    const formatDate = (value) => {
        if (!value) return "";
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return "";
        return new Intl.DateTimeFormat("ru-RU", {
            day: "2-digit",
            month: "2-digit",
            year: "numeric",
            hour: "2-digit",
            minute: "2-digit",
        }).format(date);
    };

    const initialsFor = (name) => {
        const parts = String(name || "")
            .trim()
            .split(/\s+/)
            .filter(Boolean)
            .slice(0, 2);
        return parts.map((part) => part[0]).join("").toUpperCase() || "?";
    };

    const renderEmpty = () => {
        const empty = document.createElement("div");
        empty.className = "prediction-comments-empty";

        const title = document.createElement("strong");
        title.textContent = "Пока нет комментариев";

        const copy = document.createElement("span");
        copy.textContent = "Будьте первым, кто обсудит этот прогноз.";

        empty.append(title, copy);
        return empty;
    };

    const buildComment = (comment) => {
        const row = document.createElement("article");
        row.className = "prediction-comment";
        row.dataset.commentId = String(comment.id);

        const avatar = document.createElement("span");
        avatar.className = "prediction-comment-avatar";

        const displayName = comment.user?.display_name || comment.user?.username || "Пользователь";
        const avatarUrl = comment.user?.avatar_url || "";

        if (avatarUrl) {
            avatar.dataset.skeletonImage = "";
            const image = document.createElement("img");
            image.src = avatarUrl;
            image.width = 40;
            image.height = 40;
            image.loading = "lazy";
            image.alt = "";
            avatar.append(image);
        } else {
            avatar.textContent = initialsFor(displayName);
        }

        const meta = document.createElement("div");
        meta.className = "prediction-comment-meta";

        const author = document.createElement("strong");
        author.textContent = displayName;

        const time = document.createElement("time");
        time.dateTime = comment.created_at || "";
        time.textContent = formatDate(comment.created_at);

        meta.append(author, time);

        const text = document.createElement("p");
        text.className = "prediction-comment-text";
        text.textContent = comment.text || "";

        row.append(avatar, meta);

        if (comment.can_delete) {
            const deleteButton = document.createElement("button");
            deleteButton.className = "prediction-comment-delete";
            deleteButton.type = "button";
            deleteButton.dataset.commentDelete = String(comment.id);
            deleteButton.textContent = "Удалить";
            deleteButton.setAttribute("aria-label", `Удалить комментарий пользователя ${displayName}`);
            row.append(deleteButton);
        }

        row.append(text);
        return row;
    };

    const watchRowImages = (row) => {
        row.querySelectorAll("[data-skeleton-image]").forEach((wrapper) => {
            window.CappersSkeleton?.watchImage(wrapper);
        });
    };

    const renderComments = (comments, { prepend = false } = {}) => {
        if (!list) return;

        if (!prepend) list.replaceChildren();

        if (!comments.length) {
            if (!prepend && !list.querySelector(".prediction-comment")) {
                list.append(renderEmpty());
            }
            return;
        }

        const fragment = document.createDocumentFragment();
        const rows = comments.map((comment) => buildComment(comment));
        rows.forEach((row) => fragment.append(row));

        if (prepend && list.firstChild) {
            list.insertBefore(fragment, list.firstChild);
        } else {
            list.append(fragment);
        }

        rows.forEach(watchRowImages);
    };

    const parsePayload = async (response) => {
        try {
            return await response.json();
        } catch {
            return {};
        }
    };

    const syncMoreButton = () => {
        if (!moreButton) return;
        moreButton.hidden = !previousPage;
        moreButton.disabled = loading;
    };

    const loadComments = async (page = LATEST_PAGE, { prepend = false } = {}) => {
        if (!commentsUrl || !list || loading) return;
        loading = true;
        syncMoreButton();
        setLoadError("");
        setListLoading(true);

        try {
            const separator = commentsUrl.includes("?") ? "&" : "?";
            const response = await fetch(`${commentsUrl}${separator}page=${page}`, {
                headers: {
                    Accept: "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
                credentials: "same-origin",
            });
            const payload = await parsePayload(response);
            if (!response.ok || !payload.ok) {
                throw new Error(payload.error || "Не удалось загрузить комментарии.");
            }

            renderComments(payload.comments || [], { prepend });
            updateCounters(payload.comments_count);
            previousPage = Number(payload.page) > 1 ? Number(payload.page) - 1 : null;
        } catch (error) {
            if (!prepend) list.replaceChildren();
            if (!prepend) list.append(renderEmpty());
            setLoadError(error.message || "Не удалось загрузить комментарии.");
        } finally {
            loading = false;
            setListLoading(false);
            syncMoreButton();
        }
    };

    const buildDeleteUrl = (commentId) => (
        deleteUrlTemplate.replace(/\/0\/delete\/$/, `/${encodeURIComponent(commentId)}/delete/`)
    );

    const deleteComment = async (button) => {
        const commentId = button.dataset.commentDelete;
        const endpoint = buildDeleteUrl(commentId);
        const csrftoken = decodeURIComponent(getCookie("csrftoken"));
        if (!commentId || !endpoint || !csrftoken || loading) return;

        loading = true;
        let needsReload = false;
        button.disabled = true;
        setLoadError("");
        setListLoading(true);

        try {
            const response = await fetch(endpoint, {
                method: "POST",
                headers: {
                    Accept: "application/json",
                    "X-CSRFToken": csrftoken,
                    "X-Requested-With": "XMLHttpRequest",
                },
                credentials: "same-origin",
            });
            const payload = await parsePayload(response);
            if (!response.ok || !payload.ok) {
                throw new Error(payload.error || "Не удалось удалить комментарий.");
            }

            button.closest("[data-comment-id]")?.remove();
            updateCounters(payload.comments_count);

            if (Number(payload.comments_count) === 0) {
                list.replaceChildren(renderEmpty());
                previousPage = null;
            } else if (!list.querySelector(".prediction-comment")) {
                needsReload = true;
            }
        } catch (error) {
            setLoadError(error.message || "Не удалось удалить комментарий.");
            button.disabled = false;
        } finally {
            loading = false;
            setListLoading(false);
            syncMoreButton();
            if (needsReload) void loadComments(LATEST_PAGE);
        }
    };

    const syncComposer = () => {
        if (!textarea || !submitButton) return;
        const length = textarea.value.length;
        if (lengthNode) lengthNode.textContent = String(length);
        submitButton.disabled = submitting || !textarea.value.trim() || length > 1000;
    };

    const submitComment = async (event) => {
        event.preventDefault();
        if (!form || !textarea || !submitButton || submitting || loading) return;

        const text = textarea.value.trim();
        if (!text) {
            setFeedback("Введите текст комментария.", "error");
            syncComposer();
            return;
        }

        const csrftoken = decodeURIComponent(getCookie("csrftoken"));
        if (!csrftoken) {
            setFeedback("Не удалось подтвердить сессию. Обновите страницу.", "error");
            return;
        }

        submitting = true;
        loading = true;
        const originalButtonText = submitButton.textContent;
        submitButton.disabled = true;
        submitButton.textContent = "Отправляем…";
        textarea.disabled = true;
        setFeedback("");
        setLoadError("");
        setListLoading(true);

        try {
            const response = await fetch(commentsUrl, {
                method: "POST",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrftoken,
                    "X-Requested-With": "XMLHttpRequest",
                },
                credentials: "same-origin",
                body: JSON.stringify({ text }),
            });
            const payload = await parsePayload(response);

            if (!response.ok || !payload.ok) {
                const kind = response.status === 429 ? "rate" : "error";
                setFeedback(payload.error || "Не удалось отправить комментарий.", kind);
                return;
            }

            const emptyState = list?.querySelector(".prediction-comments-empty");
            emptyState?.remove();

            if (payload.comment && list) {
                const row = buildComment(payload.comment);
                list.append(row);
                watchRowImages(row);
            }

            updateCounters(payload.comments_count);
            textarea.value = "";
            setFeedback("Комментарий опубликован.", "success");
        } catch {
            setFeedback("Не удалось отправить комментарий. Попробуйте ещё раз.", "error");
        } finally {
            submitting = false;
            loading = false;
            textarea.disabled = false;
            submitButton.textContent = originalButtonText;
            setListLoading(false);
            syncComposer();
            syncMoreButton();
        }
    };

    textarea?.addEventListener("input", () => {
        setFeedback("");
        syncComposer();
    });

    form?.addEventListener("submit", submitComment);

    moreButton?.addEventListener("click", () => {
        if (previousPage) void loadComments(previousPage, { prepend: true });
    });

    list?.addEventListener("click", (event) => {
        const button = event.target.closest("[data-comment-delete]");
        if (button) void deleteComment(button);
    });

    syncComposer();
    syncMoreButton();
})();
