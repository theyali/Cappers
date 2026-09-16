(() => {
    const root = document.querySelector("[data-prediction-comments]");
    if (!root) return;

    const list = root.querySelector("[data-comments-list]");
    const form = root.querySelector("[data-comment-form]");
    const textarea = root.querySelector("[data-comment-text]");
    const submitButton = root.querySelector("[data-comment-submit]");
    const lengthNode = root.querySelector("[data-comment-length]");
    const feedback = root.querySelector("[data-comment-feedback]");
    const replyingNode = root.querySelector("[data-comment-replying]");
    const replyingNameNode = root.querySelector("[data-comment-replying-name]");
    const replyCancelButton = root.querySelector("[data-comment-reply-cancel]");
    const loadError = root.querySelector("[data-comments-load-error]");
    const moreButton = root.querySelector("[data-comments-more]");
    const totalNode = root.querySelector("[data-comments-total]");
    const totalLabel = root.querySelector("[data-comments-total-label]");
    const commentsUrl = root.dataset.commentsUrl || "";
    const deleteUrlTemplate = root.dataset.deleteUrlTemplate || "";
    const reactionUrlTemplate = root.dataset.reactionUrlTemplate || "";
    const repliesUrlTemplate = root.dataset.repliesUrlTemplate || "";
    const predictionId = root.dataset.predictionId || "";
    const authorId = root.dataset.authorId || "";
    const LATEST_PAGE = 999999999;

    let previousPage = Number.parseInt(root.dataset.previousPage || "", 10) || null;
    let loading = false;
    let submitting = false;
    let replyParentId = null;
    let totalCount = Number.parseInt(totalNode?.textContent || "0", 10) || 0;
    let rootTotalCount = Number.parseInt(root.dataset.rootCommentsCount || "0", 10) || 0;

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

        totalCount = safeCount;
        if (totalNode) totalNode.textContent = String(safeCount);
        if (totalLabel) {
            totalLabel.textContent = russianPlural(safeCount, "комментарий", "комментария", "комментариев");
        }

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

    const updateRootCounter = (count) => {
        const parsed = Number.parseInt(count, 10);
        if (Number.isFinite(parsed)) {
            rootTotalCount = Math.max(0, parsed);
        }
    };

    const russianPlural = (value, one, few, many) => {
        const absolute = Math.abs(Number(value) || 0);
        const mod100 = absolute % 100;
        const mod10 = absolute % 10;
        if (mod100 >= 11 && mod100 <= 14) return many;
        if (mod10 === 1) return one;
        if (mod10 >= 2 && mod10 <= 4) return few;
        return many;
    };

    const formatDate = (value) => {
        if (!value) return "";
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return "";

        const diffMs = Math.max(0, Date.now() - date.getTime());
        const minutes = Math.floor(diffMs / 60000);
        if (minutes < 1) return "только что";
        if (minutes < 60) {
            return `${minutes} ${russianPlural(minutes, "минуту", "минуты", "минут")} назад`;
        }

        const hours = Math.floor(minutes / 60);
        if (hours < 24) {
            return `${hours} ${russianPlural(hours, "час", "часа", "часов")} назад`;
        }

        const days = Math.floor(hours / 24);
        if (days < 7) {
            return `${days} ${russianPlural(days, "день", "дня", "дней")} назад`;
        }

        return new Intl.DateTimeFormat("ru-RU", {
            day: "2-digit",
            month: "2-digit",
            year: "numeric",
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

    const buildComment = (comment, { isReply = false } = {}) => {
        const row = document.createElement("article");
        row.className = isReply ? "prediction-comment prediction-comment-reply-item" : "prediction-comment";
        row.dataset.commentId = String(comment.id);

        const avatar = document.createElement("a");
        avatar.className = "prediction-comment-avatar";

        const displayName = comment.user?.display_name || comment.user?.username || "Пользователь";
        const avatarUrl = comment.user?.avatar_url || "";
        const profileUrl = comment.user?.profile_url || "#";
        avatar.href = profileUrl;
        avatar.setAttribute("aria-label", `Открыть профиль ${displayName}`);

        if (avatarUrl) {
            avatar.dataset.skeletonImage = "";
            const image = document.createElement("img");
            image.src = avatarUrl;
            image.width = 52;
            image.height = 52;
            image.loading = "lazy";
            image.alt = "";
            avatar.append(image);
        } else {
            avatar.textContent = initialsFor(displayName);
        }

        const meta = document.createElement("div");
        meta.className = "prediction-comment-meta";

        const authorLink = document.createElement("a");
        authorLink.className = "prediction-comment-author-link";
        authorLink.href = profileUrl;

        const author = document.createElement("strong");
        author.textContent = displayName;
        authorLink.append(author);

        const time = document.createElement("time");
        time.dateTime = comment.created_at || "";
        time.textContent = formatDate(comment.created_at);

        meta.append(authorLink);
        if (String(comment.user?.id || "") === authorId) {
            const authorBadge = document.createElement("span");
            authorBadge.className = "prediction-comment-author-badge";
            authorBadge.textContent = "Автор";
            meta.append(authorBadge);
        }
        meta.append(time);

        const text = document.createElement("p");
        text.className = "prediction-comment-text";
        text.textContent = comment.text || "";

        const actions = buildCommentActions(comment, { allowReply: !isReply });

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

        row.append(text, actions);
        if (!isReply) row.append(buildReplies(comment));
        return row;
    };

    const buildCommentActions = (comment, { allowReply = true } = {}) => {
        const actions = document.createElement("div");
        actions.className = "prediction-comment-actions";
        actions.setAttribute("aria-label", "Реакции на комментарий");

        actions.append(
            buildReactionButton(comment, "like", comment.likes_count || 0, "Поставить лайк"),
            buildReactionButton(comment, "dislike", comment.dislikes_count || 0, "Поставить дизлайк"),
        );
        if (allowReply) {
            const replyButton = document.createElement("button");
            replyButton.className = "prediction-comment-reply";
            replyButton.type = "button";
            replyButton.dataset.commentReply = String(comment.id);
            replyButton.dataset.commentReplyName = comment.user?.display_name || comment.user?.username || "Пользователь";
            replyButton.textContent = "Ответить";
            actions.append(replyButton);
        }
        return actions;
    };

    const buildReplies = (comment) => {
        const replies = document.createElement("div");
        replies.className = "prediction-comment-replies";
        replies.dataset.commentReplies = String(comment.id);
        (comment.replies || []).forEach((reply) => {
            replies.append(buildComment(reply, { isReply: true }));
        });
        const moreButton = buildRepliesMoreButton(comment);
        if (moreButton) replies.append(moreButton);
        return replies;
    };

    const buildRepliesMoreButton = (comment) => {
        if (!comment.replies_has_next || !comment.replies_next_page) return null;
        const link = document.createElement("a");
        link.className = "prediction-comment-replies-more";
        link.href = "#";
        link.dataset.commentRepliesMore = String(comment.id);
        link.dataset.repliesPage = String(comment.replies_next_page);
        link.append(document.createTextNode(replyCountLabel(comment.replies_count || 0)));
        const arrow = document.createElement("span");
        arrow.setAttribute("aria-hidden", "true");
        arrow.textContent = "⌄";
        link.append(document.createTextNode(" "), arrow);
        return link;
    };

    const replyCountLabel = (count) => {
        const safeCount = Math.max(0, Number(count) || 0);
        return `${safeCount} ${russianPlural(safeCount, "ответ", "ответа", "ответов")}`;
    };

    const buildReactionButton = (comment, kind, count, label) => {
        const button = document.createElement("button");
        button.className = "prediction-comment-reaction";
        button.type = "button";
        button.dataset.commentReaction = String(comment.id);
        button.dataset.reactionKind = kind;
        button.setAttribute("aria-label", label);
        const isActive = comment.viewer_reaction === kind;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");

        const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        icon.setAttribute("viewBox", "0 0 24 24");
        icon.setAttribute("aria-hidden", "true");
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute(
            "d",
            kind === "like"
                ? "M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3m0 11V10l5-8a3 3 0 0 1 3 3v4h4a3 3 0 0 1 3 3l-1 7a3 3 0 0 1-3 3H7Z"
                : "M17 2h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3m0-11v12l-5 8a3 3 0 0 1-3-3v-4H5a3 3 0 0 1-3-3l1-7a3 3 0 0 1 3-3h11Z",
        );
        icon.append(path);

        const counter = document.createElement("span");
        counter.dataset[kind === "like" ? "commentLikes" : "commentDislikes"] = "";
        counter.textContent = String(count);

        button.append(icon, counter);
        return button;
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
        if (!previousPage) {
            if (!moreButton.hidden) {
                moreButton.classList.add("is-hiding");
                window.setTimeout(() => {
                    moreButton.hidden = true;
                    moreButton.classList.remove("is-hiding");
                }, 180);
            }
            return;
        }
        moreButton.hidden = false;
        moreButton.classList.remove("is-hiding");
        moreButton.disabled = loading;

        const shownCount = list?.querySelectorAll(":scope > .prediction-comment:not(.prediction-comment-reply-item)").length || 0;
        const remaining = Math.max(0, rootTotalCount - shownCount);
        moreButton.textContent = `Показать ещё комментарии${remaining ? ` (${remaining})` : ""}`;
    };

    const loadComments = async (page = LATEST_PAGE, { prepend = false } = {}) => {
        if (!commentsUrl || !list || loading) return;
        loading = true;
        syncMoreButton();
        setLoadError("");

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
            updateRootCounter(payload.root_comments_count);
            previousPage = Number(payload.page) > 1 ? Number(payload.page) - 1 : null;
        } catch (error) {
            if (!prepend) list.replaceChildren();
            if (!prepend) list.append(renderEmpty());
            setLoadError(error.message || "Не удалось загрузить комментарии.");
        } finally {
            loading = false;
            syncMoreButton();
        }
    };

    const buildDeleteUrl = (commentId) => (
        deleteUrlTemplate.replace(/\/0\/delete\/$/, `/${encodeURIComponent(commentId)}/delete/`)
    );

    const buildReactionUrl = (commentId) => (
        reactionUrlTemplate.replace(/\/0\/reaction\/$/, `/${encodeURIComponent(commentId)}/reaction/`)
    );

    const buildRepliesUrl = (commentId) => (
        repliesUrlTemplate.replace(/\/0\/replies\/$/, `/${encodeURIComponent(commentId)}/replies/`)
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
            updateRootCounter(payload.root_comments_count);

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

    const syncCommentReaction = (comment) => {
        const row = list?.querySelector(`[data-comment-id="${CSS.escape(String(comment.id))}"]`);
        if (!row) return;

        row.querySelectorAll("[data-comment-reaction]").forEach((button) => {
            const kind = button.dataset.reactionKind || "";
            const active = comment.viewer_reaction === kind;
            button.classList.toggle("is-active", active);
            button.setAttribute("aria-pressed", active ? "true" : "false");
            const countNode = button.querySelector(
                kind === "like" ? "[data-comment-likes]" : "[data-comment-dislikes]",
            );
            if (countNode) {
                countNode.textContent = String(
                    kind === "like" ? comment.likes_count || 0 : comment.dislikes_count || 0,
                );
            }
        });
    };

    const toggleCommentReaction = async (button) => {
        const commentId = button.dataset.commentReaction;
        const kind = button.dataset.reactionKind || "";
        const endpoint = buildReactionUrl(commentId);
        const csrftoken = decodeURIComponent(getCookie("csrftoken"));
        if (!commentId || !kind || !endpoint || !csrftoken || loading) return;

        loading = true;
        button.classList.add("is-loading");
        button.setAttribute("aria-busy", "true");
        setLoadError("");

        try {
            const response = await fetch(endpoint, {
                method: "POST",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrftoken,
                    "X-Requested-With": "XMLHttpRequest",
                },
                credentials: "same-origin",
                body: JSON.stringify({ kind }),
            });
            const payload = await parsePayload(response);
            if (!response.ok || !payload.ok) {
                throw new Error(payload.error || "Не удалось сохранить реакцию.");
            }
            if (payload.comment) syncCommentReaction(payload.comment);
        } catch (error) {
            setLoadError(error.message || "Не удалось сохранить реакцию.");
        } finally {
            loading = false;
            button.disabled = false;
        }
    };

    const loadReplies = async (button) => {
        const parentId = button.dataset.commentRepliesMore;
        const page = button.dataset.repliesPage;
        const endpoint = buildRepliesUrl(parentId);
        if (!parentId || !page || !endpoint || loading) return;

        loading = true;
        button.disabled = true;
        setLoadError("");

        try {
            const separator = endpoint.includes("?") ? "&" : "?";
            const response = await fetch(`${endpoint}${separator}page=${encodeURIComponent(page)}`, {
                headers: {
                    Accept: "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
                credentials: "same-origin",
            });
            const payload = await parsePayload(response);
            if (!response.ok || !payload.ok) {
                throw new Error(payload.error || "Не удалось загрузить ответы.");
            }

            const replies = list?.querySelector(`[data-comment-replies="${CSS.escape(String(parentId))}"]`);
            (payload.replies || []).forEach((reply) => {
                const row = buildComment(reply, { isReply: true });
                row.classList.add("is-new");
                replies?.insertBefore(row, button);
                watchRowImages(row);
            });

            if (payload.has_next && payload.next_page) {
                button.dataset.repliesPage = String(payload.next_page);
                const shown = replies?.querySelectorAll(":scope > .prediction-comment-reply-item").length || 0;
                const remaining = Math.max(0, Number(payload.replies_count || 0) - shown);
                button.firstChild.nodeValue = `${replyCountLabel(remaining)} `;
                button.classList.remove("is-loading");
                button.removeAttribute("aria-busy");
            } else {
                button.remove();
            }
        } catch (error) {
            setLoadError(error.message || "Не удалось загрузить ответы.");
            button.classList.remove("is-loading");
            button.removeAttribute("aria-busy");
        } finally {
            loading = false;
            syncMoreButton();
        }
    };

    const syncComposer = () => {
        if (!textarea || !submitButton) return;
        const length = textarea.value.length;
        if (lengthNode) lengthNode.textContent = String(length);
        submitButton.disabled = submitting || !textarea.value.trim() || length > 1000;
    };

    const setReplyTarget = (parentId = null, displayName = "") => {
        replyParentId = parentId ? String(parentId) : null;
        if (!replyingNode) return;
        replyingNode.hidden = !replyParentId;
        if (replyingNameNode) replyingNameNode.textContent = displayName || "";
        if (replyParentId && textarea) {
            textarea.focus();
        }
    };

    const submitComment = async (event) => {
        event.preventDefault();
        if (!form || !textarea || !submitButton || submitting) return;

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
        submitButton.disabled = true;
        submitButton.setAttribute("aria-label", "Отправляем комментарий");
        textarea.disabled = true;
        setFeedback("");
        setLoadError("");

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
                body: JSON.stringify({ text, parent_id: replyParentId }),
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
                const isReply = Boolean(payload.comment.parent_id);
                const row = buildComment(payload.comment, { isReply });
                row.classList.add("is-new");
                if (isReply) {
                    const replies = list.querySelector(
                        `[data-comment-replies="${CSS.escape(String(payload.comment.parent_id))}"]`,
                    );
                    const moreReplies = replies?.querySelector("[data-comment-replies-more]");
                    if (moreReplies) {
                        replies.insertBefore(row, moreReplies);
                    } else {
                        replies?.append(row);
                    }
                } else {
                    list.append(row);
                }
                watchRowImages(row);
            }

            updateCounters(payload.comments_count);
            updateRootCounter(payload.root_comments_count);
            textarea.value = "";
            setReplyTarget(null);
            setFeedback("Комментарий опубликован.", "success");
        } catch {
            setFeedback("Не удалось отправить комментарий. Попробуйте ещё раз.", "error");
        } finally {
            submitting = false;
            textarea.disabled = false;
            submitButton.setAttribute("aria-label", "Отправить комментарий");
            syncComposer();
            syncMoreButton();
        }
    };

    textarea?.addEventListener("input", () => {
        setFeedback("");
        syncComposer();
    });

    form?.addEventListener("submit", submitComment);

    replyCancelButton?.addEventListener("click", () => {
        setReplyTarget(null);
    });

    moreButton?.addEventListener("click", () => {
        if (previousPage) void loadComments(previousPage, { prepend: true });
    });

    list?.addEventListener("click", (event) => {
        const button = event.target.closest("[data-comment-delete]");
        if (button) void deleteComment(button);
        const reactionButton = event.target.closest("[data-comment-reaction]");
        if (reactionButton) void toggleCommentReaction(reactionButton);
        const replyButton = event.target.closest("[data-comment-reply]");
        if (replyButton) {
            setReplyTarget(replyButton.dataset.commentReply, replyButton.dataset.commentReplyName || "");
        }
        const repliesMoreButton = event.target.closest("[data-comment-replies-more]");
        if (repliesMoreButton) {
            event.preventDefault();
            void loadReplies(repliesMoreButton);
        }
    });

    updateCounters(totalCount);
    updateRootCounter(rootTotalCount);
    syncComposer();
    syncMoreButton();
})();
