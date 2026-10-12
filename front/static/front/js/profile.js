(() => {
    const page = document.querySelector(".profile-page");
    const input = document.getElementById("avatarUploadInput");
    const status = document.getElementById("profileAvatarStatus");

    if (!page) return;

    const initPaidPlansVisibility = () => {
        const toggle = page.querySelector("[data-paid-predictions-toggle] input[type='checkbox']");
        const plans = page.querySelector("[data-paid-predictions-plans]");
        if (!toggle || !plans) return;

        const sync = () => {
            plans.classList.toggle("is-collapsed", !toggle.checked);
            plans.setAttribute("aria-hidden", toggle.checked ? "false" : "true");
        };

        sync();
        toggle.addEventListener("change", sync);
    };

    initPaidPlansVisibility();

    const initProfileEditTabs = () => {
        const tabs = Array.from(page.querySelectorAll("[data-profile-edit-tab]"));
        const panels = Array.from(page.querySelectorAll("[data-profile-edit-panel]"));
        if (!tabs.length || !panels.length) return null;

        const activate = (target) => {
            const hasTarget = panels.some((panel) => panel.dataset.profileEditPanel === target);
            const nextTarget = hasTarget ? target : panels[0].dataset.profileEditPanel;

            tabs.forEach((tab) => {
                const isActive = tab.dataset.profileEditTab === nextTarget;
                tab.classList.toggle("is-active", isActive);
                tab.setAttribute("aria-selected", isActive ? "true" : "false");
            });

            panels.forEach((panel) => {
                const isActive = panel.dataset.profileEditPanel === nextTarget;
                panel.hidden = !isActive;
                panel.classList.toggle("is-entering", isActive);
                if (isActive) {
                    window.setTimeout(() => panel.classList.remove("is-entering"), 220);
                }
            });
        };

        tabs.forEach((tab) => {
            tab.addEventListener("click", (event) => {
                event.preventDefault();
                activate(tab.dataset.profileEditTab);
            });
        });

        const panelFromHash = window.location.hash
            ? panels.find((panel) => `#${panel.id}` === window.location.hash)
            : null;
        const panelWithErrors = panels.find((panel) => panel.querySelector(".errorlist"));
        const initial = panelFromHash?.dataset.profileEditPanel
            || panelWithErrors?.dataset.profileEditPanel
            || tabs.find((tab) => tab.classList.contains("is-active"))?.dataset.profileEditTab;
        activate(initial || tabs[0].dataset.profileEditTab);
        return activate;
    };

    const activateProfileEditTab = initProfileEditTabs();

    const initMobileQuickAccessLimit = () => {
        const wrapper = page.querySelector("[data-mobile-quick-access-options]");
        if (!wrapper) return;

        const limit = Number.parseInt(wrapper.dataset.max || "4", 10);
        const checkboxes = Array.from(wrapper.querySelectorAll("input[type='checkbox']"));
        if (!Number.isFinite(limit) || limit <= 0 || !checkboxes.length) return;

        const sync = () => {
            const selectedCount = checkboxes.filter((checkbox) => checkbox.checked).length;
            const limitReached = selectedCount >= limit;
            checkboxes.forEach((checkbox) => {
                const isLocked = limitReached && !checkbox.checked;
                checkbox.disabled = isLocked;
                checkbox.closest("li")?.classList.toggle("is-disabled", isLocked);
            });
        };

        checkboxes.forEach((checkbox) => {
            checkbox.addEventListener("change", sync);
        });
        sync();
    };

    initMobileQuickAccessLimit();

    const loadJQuery = () => {
        if (window.jQuery) return Promise.resolve(window.jQuery);

        return new Promise((resolve, reject) => {
            let script = document.querySelector("script[data-profile-jquery]");
            if (!script) {
                script = document.createElement("script");
                script.src = "https://code.jquery.com/jquery-3.7.1.min.js";
                script.dataset.profileJquery = "true";
                script.async = true;
                document.head.appendChild(script);
            }

            const onLoad = () => {
                if (window.jQuery) {
                    resolve(window.jQuery);
                } else {
                    reject(new Error("jQuery не загрузился."));
                }
            };
            const onError = () => reject(new Error("Не удалось загрузить jQuery."));

            if (window.jQuery) {
                resolve(window.jQuery);
                return;
            }

            script.addEventListener("load", onLoad, { once: true });
            script.addEventListener("error", onError, { once: true });
        });
    };

    // Settings forms save in the background; without jQuery they post as usual.
    const initSettingsAjax = ($) => {
        const profileForm = page.querySelector(".profile-edit-form");
        const quickAccessForm = document.getElementById("mobileQuickAccessForm");
        const verificationForm = document.getElementById("profileVerificationForm");

        const showStatus = (statusBox, kind, text) => {
            if (!statusBox) return;
            $(statusBox).empty().append($("<p>", { class: `message-item ${kind}`, text }));
        };

        const clearErrors = () => {
            $(profileForm).find(".errorlist, .profile-form-alert").remove();
        };

        const fieldContainer = (form, name) => {
            const field = Array.from(form.elements).find((element) => element.name === name);
            if (!field) return null;
            return field.closest(".profile-field, .profile-paid-plan-price, .profile-quick-access-field") || field.parentElement;
        };

        const showErrors = (form, response, statusBox) => {
            const unplaced = [];
            let firstContainer = null;
            Object.entries(response.errors || {}).forEach(([name, messages]) => {
                const container = fieldContainer(form, name);
                if (!container) {
                    unplaced.push(...messages);
                    return;
                }
                const $list = $("<ul>", { class: "errorlist" });
                messages.forEach((message) => $list.append($("<li>", { text: message })));
                $(container).append($list);
                firstContainer = firstContainer || container;
            });
            const details = [...(response.non_field_errors || []), ...unplaced];
            showStatus(statusBox, "error", [response.message || "Не удалось сохранить.", ...details].join(" "));

            if (!firstContainer) return;
            const panel = firstContainer.closest("[data-profile-edit-panel]");
            if (panel && activateProfileEditTab) {
                activateProfileEditTab(panel.dataset.profileEditPanel);
            }
            firstContainer.scrollIntoView({ behavior: "smooth", block: "center" });
        };

        const bindAjaxForm = (form, statusBoxFor, onSuccess) => {
            if (!form) return;
            $(form).on("submit", (event) => {
                event.preventDefault();
                if (form.dataset.saving === "true") return;

                const $buttons = $(Array.from(form.elements).filter((element) => element.type === "submit"));
                form.dataset.saving = "true";
                $buttons.prop("disabled", true).attr("aria-busy", "true");

                $.ajax({
                    url: form.action,
                    method: "POST",
                    data: $(form).serialize(),
                    dataType: "json",
                })
                    .done((response) => {
                        clearErrors();
                        onSuccess(response);
                        showStatus(statusBoxFor(), "success", response.message || "Сохранено.");
                    })
                    .fail((xhr) => {
                        clearErrors();
                        const response = xhr.responseJSON;
                        if (response) {
                            replaceVerification(response.verification_html);
                            showErrors(form, response, statusBoxFor());
                        } else {
                            showStatus(statusBoxFor(), "error", "Не удалось сохранить. Проверьте соединение и попробуйте ещё раз.");
                        }
                    })
                    .always(() => {
                        delete form.dataset.saving;
                        $buttons.prop("disabled", false).removeAttr("aria-busy");
                    });
            });
        };

        const replaceVerification = (html) => {
            if (html) $("[data-profile-verification]").replaceWith(html);
        };

        bindAjaxForm(
            profileForm,
            () => profileForm.querySelector(":scope > [data-profile-save-status]"),
            (response) => {
                if (response.profile_name) $("[data-profile-name]").text(response.profile_name);
                if (typeof response.profile_completion === "number") {
                    const percent = `${response.profile_completion}%`;
                    $(".profile-edit-completion strong").text(percent);
                    $(".profile-completion-progress").val(response.profile_completion).text(percent);
                }
                replaceVerification(response.verification_html);
            }
        );

        bindAjaxForm(
            quickAccessForm,
            () => page.querySelector("#profile-edit-quick-access [data-profile-save-status]"),
            (response) => {
                if (response.quick_access_html) {
                    $("[data-mobile-quick-access-grid]").replaceWith(response.quick_access_html);
                }
            }
        );

        bindAjaxForm(
            verificationForm,
            () => page.querySelector("[data-profile-verification] [data-profile-save-status]"),
            (response) => {
                replaceVerification(response.verification_html);
                const $nameLine = $("[data-profile-name-line]");
                if (response.badge_html && !$nameLine.find(".capper-verified-badge").length) {
                    $nameLine.append(response.badge_html);
                }
            }
        );
    };

    if (page.querySelector(".profile-edit-form")) {
        loadJQuery()
            .then(initSettingsAjax)
            .catch((error) => console.error(error));
    }

    const tabLinks = Array.from(document.querySelectorAll("[data-profile-tab-link]"));
    const tabPanels = Array.from(document.querySelectorAll("[data-profile-tab-panel]"));

    const markProfileSectionRead = async (panel) => {
        if (!panel?.dataset.profileSectionReadUrl || panel.dataset.readSynced === "true") return;
        panel.dataset.readSynced = "true";
        try {
            const response = await fetch(panel.dataset.profileSectionReadUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "X-CSRFToken": getCookie("csrftoken"),
                    "X-Requested-With": "XMLHttpRequest",
                },
            });
            const payload = await response.json().catch(() => ({}));
            if (response.ok && payload?.ok) {
                syncNotificationBadges(payload);
                window.dispatchEvent(new Event("cappers:notifications-changed"));
            }
        } catch (error) {}
    };

    const activateTab = (tab) => {
        let activePanel = null;
        tabPanels.forEach((panel) => {
            const isActive = panel.dataset.profileTabPanel === tab;
            panel.classList.toggle("is-active", isActive);
            if (isActive) activePanel = panel;
        });

        tabLinks.forEach((link) => {
            const target = new URL(link.href, window.location.href).searchParams.get("tab") || "profile";
            link.classList.toggle("is-active", target === tab);
        });

        markProfileSectionRead(activePanel);
        window.dispatchEvent(new CustomEvent("profile:tab-activated", { detail: { tab } }));
    };

    tabLinks.forEach((link) => {
        link.addEventListener("click", (event) => {
            const url = new URL(link.href, window.location.href);
            const tab = url.searchParams.get("tab") || "profile";
            if (!tabPanels.some((panel) => panel.dataset.profileTabPanel === tab)) return;

            event.preventDefault();
            window.history.pushState({}, "", url);
            activateTab(tab);
        });
    });

    window.addEventListener("popstate", () => {
        const tab = new URL(window.location.href).searchParams.get("tab") || "profile";
        activateTab(tab);
    });

    const applyProfileListFilters = (listName) => {
        const list = document.querySelector(`[data-profile-list="${listName}"]`);
        if (!list) return;

        const searchInput = document.querySelector(`[data-profile-list-search="${listName}"]`);
        const newFilter = document.querySelector(`[data-profile-new-filter="${listName}"]`);
        const query = (searchInput?.value || "").trim().toLowerCase();
        const onlyNew = Boolean(newFilter?.classList.contains("is-active"));

        list.querySelectorAll("[data-profile-username]").forEach((row) => {
            const matchesQuery = query === "" || (row.dataset.profileUsername || "").includes(query);
            const matchesNew = !onlyNew || row.dataset.profileHasNew === "true";
            row.classList.toggle("is-hidden", !matchesQuery || !matchesNew);
        });
    };
    window.CappersProfileApplyListFilters = applyProfileListFilters;

    const syncNotificationBadges = (payload = {}) => {
        if (payload.section_badges) {
            document.querySelectorAll("[data-notification-section-badge]").forEach((dot) => {
                const section = dot.dataset.notificationSectionBadge || "";
                dot.classList.toggle("is-empty", !payload.section_badges[section]);
            });
        }
        if (Object.prototype.hasOwnProperty.call(payload, "unread_count")) {
            const count = Math.max(0, Number.parseInt(payload.unread_count, 10) || 0);
            document.querySelectorAll("[data-notification-badge]").forEach((badge) => {
                badge.textContent = count > 99 ? "99+" : String(count);
                badge.classList.toggle("is-empty", count === 0);
            });
        }
    };

    document.querySelectorAll("[data-profile-list-search]").forEach((searchInput) => {
        searchInput.addEventListener("input", () => {
            applyProfileListFilters(searchInput.dataset.profileListSearch);
        });
    });

    document.querySelectorAll("[data-profile-new-filter]").forEach((button) => {
        button.addEventListener("click", async () => {
            if (button.disabled && !button.classList.contains("is-active")) return;

            const listName = button.dataset.profileNewFilter;
            const nextActive = !button.classList.contains("is-active");
            button.classList.toggle("is-active", nextActive);
            button.setAttribute("aria-pressed", nextActive ? "true" : "false");
            button.querySelector("span").textContent = nextActive ? "Все подписки" : "Показать новые";
            applyProfileListFilters(listName);

            if (!nextActive || button.dataset.readSynced === "true" || !button.dataset.markReadUrl) return;

            button.dataset.readSynced = "true";
            try {
                const response = await fetch(button.dataset.markReadUrl, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        "X-CSRFToken": getCookie("csrftoken"),
                        "X-Requested-With": "XMLHttpRequest",
                    },
                });
                const payload = await response.json().catch(() => ({}));
                if (response.ok && payload?.ok) {
                    syncNotificationBadges(payload);
                    window.dispatchEvent(new Event("cappers:notifications-changed"));
                }
            } catch (error) {}
        });
    });

    const getCookie = (name) => {
        const cookies = document.cookie ? document.cookie.split(";") : [];
        for (const cookie of cookies) {
            const trimmed = cookie.trim();
            if (trimmed.startsWith(`${name}=`)) {
                return decodeURIComponent(trimmed.slice(name.length + 1));
            }
        }
        return "";
    };

    const profileModalOpenButtons = Array.from(document.querySelectorAll("[data-profile-modal-open]"));
    const profileModalCloseButtons = Array.from(document.querySelectorAll("[data-profile-modal-close]"));
    let profileModalCloseTimer = 0;

    const openProfileModal = (modal) => {
        if (!modal) return;
        window.clearTimeout(profileModalCloseTimer);
        modal.classList.remove("is-open", "is-closing");
        modal.classList.add("is-preparing");
        modal.offsetHeight;
        modal.classList.remove("is-preparing");
        modal.classList.add("is-open");
        modal.setAttribute("aria-hidden", "false");
        document.documentElement.classList.add("is-profile-modal-open");
        window.setTimeout(() => {
            modal.querySelector("[data-profile-modal-close]")?.focus();
        }, 40);
    };

    const closeProfileModal = (modal) => {
        if (!modal || !modal.classList.contains("is-open")) return;
        modal.classList.remove("is-open", "is-preparing");
        modal.classList.add("is-closing");
        modal.setAttribute("aria-hidden", "true");
        document.documentElement.classList.remove("is-profile-modal-open");
        window.clearTimeout(profileModalCloseTimer);
        profileModalCloseTimer = window.setTimeout(() => {
            modal.classList.remove("is-closing");
            const statusNode = modal.querySelector("[data-profile-email-request-status]");
            if (statusNode) {
                statusNode.textContent = "";
                statusNode.classList.remove("is-error");
            }
        }, 240);
    };

    profileModalOpenButtons.forEach((button) => {
        button.addEventListener("click", (event) => {
            event.preventDefault();
            openProfileModal(document.getElementById(button.dataset.profileModalOpen || ""));
        });
    });

    profileModalCloseButtons.forEach((button) => {
        button.addEventListener("click", (event) => {
            event.preventDefault();
            closeProfileModal(button.closest(".profile-email-modal"));
        });
    });

    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        const openedModal = document.querySelector(".profile-email-modal.is-open");
        if (openedModal && openedModal.id !== "profile-avatar-modal") closeProfileModal(openedModal);
    });

    const requestedProfileModal = window.location.hash
        ? document.getElementById(window.location.hash.slice(1))
        : null;
    if (requestedProfileModal && requestedProfileModal.id !== "profile-avatar-modal") {
        window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
        openProfileModal(requestedProfileModal);
    }

    document.querySelectorAll("[data-profile-email-request-form]").forEach((form) => {
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (form.dataset.sending === "true") return;

            const submitButton = form.querySelector(".profile-email-modal-submit");
            const statusNode = form.querySelector("[data-profile-email-request-status]");
            form.dataset.sending = "true";
            submitButton?.setAttribute("disabled", "disabled");
            if (statusNode) {
                statusNode.textContent = "Отправляем ссылку...";
                statusNode.classList.remove("is-error");
            }

            try {
                const response = await fetch(form.action, {
                    method: "POST",
                    body: new FormData(form),
                    credentials: "same-origin",
                    headers: {
                        "X-CSRFToken": getCookie("csrftoken"),
                        "X-Requested-With": "XMLHttpRequest",
                    },
                });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok || !payload.ok) {
                    throw new Error(payload.error || "Не удалось отправить ссылку.");
                }
                if (statusNode) statusNode.textContent = payload.message || "Ссылка отправлена. Проверьте почту.";
            } catch (error) {
                if (statusNode) {
                    statusNode.textContent = error.message || "Не удалось отправить ссылку.";
                    statusNode.classList.add("is-error");
                }
            } finally {
                delete form.dataset.sending;
                submitButton?.removeAttribute("disabled");
            }
        });
    });

    document.querySelectorAll("[data-follow-url]").forEach((button) => {
        if (button.closest("[data-profile-social]")) return;
        button.addEventListener("click", async () => {
            if (button.disabled) return;

            const originalText = button.textContent;
            button.disabled = true;
            button.textContent = "Подписываем...";

            try {
                const response = await fetch(button.dataset.followUrl, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        "X-CSRFToken": getCookie("csrftoken"),
                        "X-Requested-With": "XMLHttpRequest",
                    },
                });
                const payload = await response.json();
                if (!response.ok || !payload.ok) {
                    throw new Error(payload.error || "Не удалось подписаться.");
                }

                button.textContent = "Вы подписаны";
                button.classList.add("is-muted");
                button.removeAttribute("data-follow-url");
            } catch (error) {
                button.textContent = error.message || originalText;
                window.setTimeout(() => {
                    button.textContent = originalText;
                    button.disabled = false;
                }, 1800);
            }
        });
    });

    if (!input || !status) return;

    const modal = document.getElementById("profile-avatar-modal");
    const uploadUrl = page.dataset.avatarUploadUrl;
    const presetForm = document.getElementById("profileAvatarPresetForm");
    const presetInput = presetForm?.querySelector("[data-avatar-preset-input]");
    const saveButton = document.querySelector("[data-avatar-save]");
    const cropSaveButton = document.querySelector("[data-avatar-crop-save]");
    const modeButtons = Array.from(document.querySelectorAll(".profile-avatar-mode-tabs [data-avatar-mode]"));
    const panelModeButtons = Array.from(document.querySelectorAll("[data-avatar-mode]"));
    const filterButtons = Array.from(document.querySelectorAll("[data-avatar-filter]"));
    const choiceButtons = Array.from(document.querySelectorAll("[data-avatar-choice]"));
    const panels = Array.from(document.querySelectorAll("[data-avatar-panel]"));
    const selectedLabel = document.querySelector("[data-avatar-selected-label]");
    const cropStage = document.querySelector("[data-avatar-crop-stage]");
    const cropImage = document.querySelector("[data-avatar-crop-image]");
    const zoomInput = document.querySelector("[data-avatar-zoom]");
    const openAvatarButtons = Array.from(document.querySelectorAll("[data-avatar-modal-open], a[href='#profile-avatar-modal']"));
    const closeAvatarButtons = Array.from(document.querySelectorAll("[data-avatar-modal-close]"));

    let activePanel = "ready";
    let pendingFile = null;
    let pendingObjectUrl = "";
    let selectedPresetId = "";
    let cropZoom = 1;
    let cropX = 0;
    let cropY = 0;
    let isDraggingCrop = false;
    let dragStartX = 0;
    let dragStartY = 0;
    let closeTimer = 0;
    let panelTimer = 0;
    let hasAvatarChanges = false;
    let currentSavedAvatarUrl = document.getElementById("profileAvatarImage")?.getAttribute("src")
        || document.querySelector(".nav-profile-icon .nav-profile-avatar-image")?.getAttribute("src")
        || "";

    const showStatus = (message, isError = false) => {
        status.textContent = message;
        status.classList.toggle("is-error", isError);
    };

    const updateAvatarSaveState = () => {
        const canSave = hasAvatarChanges && !isSavingAvatar;
        saveButton?.toggleAttribute("disabled", !canSave);
        cropSaveButton?.toggleAttribute("disabled", !pendingFile || isSavingAvatar);
    };

    const updatePreviewNode = (node, url, size, alt) => {
        if (!node || !url) return;
        let image = node.querySelector("img");
        if (!image) {
            node.textContent = "";
            image = document.createElement("img");
            image.width = size;
            image.height = size;
            image.alt = alt;
            image.decoding = "async";
            node.appendChild(image);
        }
        image.src = url;
    };

    const setModalPreview = (url) => {
        updatePreviewNode(document.querySelector("[data-avatar-current]"), url, 148, "Ваш текущий аватар");
        updatePreviewNode(document.querySelector("[data-avatar-current-mini]"), url, 36, "");
        updatePreviewNode(document.querySelector("[data-avatar-crop-preview]"), url, 148, "");
    };

    const fadeImageSource = (image, url) => {
        if (!image || !url) return;
        const shell = image.closest(".profile-avatar, .nav-profile-icon, .nav-profile-dropdown-avatar") || image;
        shell.classList.add("is-avatar-updating");
        const nextImage = new Image();
        nextImage.onload = () => {
            image.src = url;
            window.requestAnimationFrame(() => {
                shell.classList.remove("is-avatar-updating");
            });
        };
        nextImage.onerror = () => {
            image.src = url;
            shell.classList.remove("is-avatar-updating");
        };
        nextImage.src = url;
    };

    const replaceAvatar = (url) => {
        const avatar = document.getElementById("profileAvatar");
        if (!avatar) return;

        let image = document.getElementById("profileAvatarImage");
        const fallback = document.getElementById("profileAvatarFallback");
        if (!image) {
            image = document.createElement("img");
            image.id = "profileAvatarImage";
            image.alt = "Аватар профиля";
            image.width = 128;
            image.height = 128;
            image.decoding = "async";
            if (fallback) fallback.remove();
            avatar.appendChild(image);
        }
        const refreshedUrl = `${url}${url.includes("?") ? "&" : "?"}v=${Date.now()}`;
        fadeImageSource(image, refreshedUrl);
        document.querySelectorAll(".nav-profile-icon > img, .site-nav-actions .nav-profile-avatar-image").forEach((navImage) => {
            navImage.classList.add("nav-profile-avatar-image");
            navImage.width = 42;
            navImage.height = 42;
            navImage.alt = navImage.alt || "";
            fadeImageSource(navImage, refreshedUrl);
            window.CappersSkeleton?.watchImage(navImage.closest("[data-skeleton-image]"));
        });
        setModalPreview(refreshedUrl);
        currentSavedAvatarUrl = refreshedUrl;
        window.CappersSkeleton?.watchImage(avatar);
    };

    const resetAvatarDraft = () => {
        if (pendingObjectUrl) {
            URL.revokeObjectURL(pendingObjectUrl);
            pendingObjectUrl = "";
        }
        pendingFile = null;
        selectedPresetId = "";
        hasAvatarChanges = false;
        if (presetInput) presetInput.value = "";
        input.value = "";
        choiceButtons.forEach((choice) => choice.classList.remove("is-selected"));
        if (selectedLabel) selectedLabel.textContent = "Выбрано: 0";
        if (currentSavedAvatarUrl) setModalPreview(currentSavedAvatarUrl);
        updateAvatarSaveState();
    };

    const openAvatarModal = () => {
        if (!modal) return;
        resetAvatarDraft();
        showPanel("ready");
        window.clearTimeout(closeTimer);
        modal.classList.remove("is-open", "is-closing");
        modal.classList.add("is-preparing");
        modal.offsetHeight;
        modal.classList.remove("is-preparing");
        modal.classList.add("is-open");
        modal.setAttribute("aria-hidden", "false");
        document.documentElement.classList.add("is-profile-avatar-modal-open");
        window.setTimeout(() => {
            modal.querySelector("[data-avatar-modal-close]")?.focus();
        }, 40);
    };

    const closeAvatarModal = () => {
        if (!modal || !modal.classList.contains("is-open")) return;
        modal.classList.remove("is-open", "is-preparing");
        modal.classList.add("is-closing");
        modal.setAttribute("aria-hidden", "true");
        document.documentElement.classList.remove("is-profile-avatar-modal-open");
        window.clearTimeout(closeTimer);
        closeTimer = window.setTimeout(() => {
            modal.classList.remove("is-closing");
            showStatus("");
            resetAvatarDraft();
        }, 240);
    };

    const showPanel = (name) => {
        if (activePanel === name) return;
        const previousPanel = panels.find((panel) => !panel.hidden);
        const nextPanel = panels.find((panel) => panel.dataset.avatarPanel === name);
        if (!nextPanel) return;
        activePanel = name;
        modeButtons.forEach((button) => {
            const isActive = button.dataset.avatarMode === name || (name === "crop" && button.dataset.avatarMode === "upload");
            button.classList.toggle("is-active", isActive);
            button.setAttribute("aria-selected", isActive ? "true" : "false");
        });
        window.clearTimeout(panelTimer);
        if (previousPanel && previousPanel !== nextPanel) {
            previousPanel.classList.remove("is-panel-entering", "is-panel-active");
            previousPanel.classList.add("is-panel-leaving");
            panelTimer = window.setTimeout(() => {
                previousPanel.hidden = true;
                previousPanel.classList.remove("is-panel-leaving");
            }, 180);
        }
        nextPanel.hidden = false;
        nextPanel.classList.add("is-panel-entering");
        window.requestAnimationFrame(() => {
            nextPanel.classList.add("is-panel-active");
        });
        window.setTimeout(() => {
            nextPanel.classList.remove("is-panel-entering", "is-panel-active");
        }, 210);
        showStatus("");
    };

    const resetCropPosition = () => {
        cropZoom = 1;
        cropX = 0;
        cropY = 0;
        if (zoomInput) zoomInput.value = "1";
        cropStage?.style.setProperty("--avatar-crop-x", "0px");
        cropStage?.style.setProperty("--avatar-crop-y", "0px");
        cropStage?.style.setProperty("--avatar-crop-zoom", "1");
    };

    const fitCropImage = () => {
        if (!cropStage || !cropImage || !cropImage.naturalWidth || !cropImage.naturalHeight) return;
        const stageRect = cropStage.getBoundingClientRect();
        const imageRatio = cropImage.naturalWidth / cropImage.naturalHeight;
        const stageRatio = stageRect.width / stageRect.height;
        let baseWidth = stageRect.width;
        let baseHeight = stageRect.height;
        if (imageRatio > stageRatio) {
            baseHeight = stageRect.height;
            baseWidth = baseHeight * imageRatio;
        } else {
            baseWidth = stageRect.width;
            baseHeight = baseWidth / imageRatio;
        }
        cropImage.style.width = `${baseWidth}px`;
        cropImage.style.height = `${baseHeight}px`;
        cropImage.dataset.baseWidth = String(baseWidth);
        cropImage.dataset.baseHeight = String(baseHeight);
    };

    const applyCropPosition = () => {
        cropStage?.style.setProperty("--avatar-crop-x", `${cropX}px`);
        cropStage?.style.setProperty("--avatar-crop-y", `${cropY}px`);
        cropStage?.style.setProperty("--avatar-crop-zoom", String(cropZoom));
    };

    const selectPreset = (button) => {
        selectedPresetId = button.dataset.avatarId || "";
        pendingFile = null;
        if (pendingObjectUrl) {
            URL.revokeObjectURL(pendingObjectUrl);
            pendingObjectUrl = "";
        }
        hasAvatarChanges = Boolean(selectedPresetId);
        if (presetInput) presetInput.value = selectedPresetId;
        choiceButtons.forEach((choice) => choice.classList.toggle("is-selected", choice === button));
        setModalPreview(button.dataset.avatarSrc || "");
        if (selectedLabel) selectedLabel.textContent = "Выбрано: 1";
        updateAvatarSaveState();
    };

    const savePresetAvatar = () => {
        if (!selectedPresetId || !presetForm) {
            showStatus("Выберите аватар.", true);
            return;
        }
        const data = new FormData(presetForm);
        data.set("preset_id", selectedPresetId);
        saveAvatar(data, "Применяем готовый аватар...");
    };

    const selectedVisibleChoice = () => choiceButtons.find((button) => (
        button.classList.contains("is-selected") && !button.hidden
    ));

    const filterAvatars = (filter) => {
        filterButtons.forEach((button) => {
            button.classList.toggle("is-active", button.dataset.avatarFilter === filter);
        });
        choiceButtons.forEach((button) => {
            const gender = button.dataset.avatarGender || "all";
            button.hidden = filter !== "all" && gender !== filter;
        });
        if (selectedLabel) {
            selectedLabel.textContent = selectedVisibleChoice() ? "Выбрано: 1" : "Выбрано: 0";
        }
    };

    const createCroppedAvatar = () => new Promise((resolve, reject) => {
        if (!pendingFile || !cropStage || !cropImage || !cropImage.naturalWidth) {
            reject(new Error("Выберите фото для кадрирования."));
            return;
        }
        const stageRect = cropStage.getBoundingClientRect();
        const baseWidth = Number.parseFloat(cropImage.dataset.baseWidth || "0");
        const baseHeight = Number.parseFloat(cropImage.dataset.baseHeight || "0");
        if (!baseWidth || !baseHeight) {
            reject(new Error("Не удалось подготовить изображение."));
            return;
        }
        const cropSize = Math.min(stageRect.width, stageRect.height) * 0.7;
        const renderedWidth = baseWidth * cropZoom;
        const renderedHeight = baseHeight * cropZoom;
        const imageLeft = stageRect.width / 2 + cropX - renderedWidth / 2;
        const imageTop = stageRect.height / 2 + cropY - renderedHeight / 2;
        const scale = renderedWidth / cropImage.naturalWidth;
        const sx = Math.max(0, ((stageRect.width - cropSize) / 2 - imageLeft) / scale);
        const sy = Math.max(0, ((stageRect.height - cropSize) / 2 - imageTop) / scale);
        const sourceSize = Math.min(
            cropImage.naturalWidth - sx,
            cropImage.naturalHeight - sy,
            cropSize / scale,
        );

        const canvas = document.createElement("canvas");
        canvas.width = 512;
        canvas.height = 512;
        const context = canvas.getContext("2d");
        context.drawImage(cropImage, sx, sy, sourceSize, sourceSize, 0, 0, 512, 512);
        canvas.toBlob((blob) => {
            if (!blob) {
                reject(new Error("Не удалось сохранить кадр."));
                return;
            }
            resolve(blob);
        }, "image/png");
    });

    let isSavingAvatar = false;
    const saveAvatar = async (data, pendingMessage) => {
        if (isSavingAvatar) return;
        isSavingAvatar = true;
        input.disabled = true;
        saveButton?.setAttribute("disabled", "disabled");
        cropSaveButton?.setAttribute("disabled", "disabled");
        presetForm?.querySelectorAll("button").forEach((button) => { button.disabled = true; });
        showStatus(pendingMessage);
        try {
            const response = await fetch(uploadUrl, {
                method: "POST",
                body: data,
                credentials: "same-origin",
                headers: {
                    "X-CSRFToken": getCookie("csrftoken"),
                    "X-Requested-With": "XMLHttpRequest",
                },
            });
            const payload = await response.json();
            if (!response.ok || !payload.ok) {
                throw new Error(payload.error || "Не удалось обновить аватар.");
            }
            replaceAvatar(payload.avatar_url);
            hasAvatarChanges = false;
            pendingFile = null;
            selectedPresetId = "";
            updateAvatarSaveState();
            showStatus(payload.message || "Аватар обновлён.");
            window.setTimeout(() => {
                closeAvatarModal();
            }, 650);
        } catch (error) {
            showStatus(error.message || "Ошибка загрузки.", true);
        } finally {
            isSavingAvatar = false;
            input.disabled = false;
            input.value = "";
            updateAvatarSaveState();
            presetForm?.querySelectorAll("button").forEach((button) => { button.disabled = false; });
        }
    };

    choiceButtons.forEach((button) => {
        button.addEventListener("click", () => selectPreset(button));
    });

    openAvatarButtons.forEach((button) => {
        button.addEventListener("click", (event) => {
            event.preventDefault();
            openAvatarModal();
        });
    });

    closeAvatarButtons.forEach((button) => {
        button.addEventListener("click", (event) => {
            event.preventDefault();
            closeAvatarModal();
        });
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && modal?.classList.contains("is-open")) {
            closeAvatarModal();
        }
    });

    filterButtons.forEach((button) => {
        button.addEventListener("click", () => filterAvatars(button.dataset.avatarFilter || "all"));
    });

    panelModeButtons.forEach((button) => {
        button.addEventListener("click", () => showPanel(button.dataset.avatarMode || "ready"));
    });

    saveButton?.addEventListener("click", async () => {
        if (activePanel === "crop" && pendingFile) {
            try {
                const blob = await createCroppedAvatar();
                const data = new FormData();
                data.append("avatar", blob, "avatar.png");
                saveAvatar(data, "Сохраняем фото...");
            } catch (error) {
                showStatus(error.message || "Не удалось сохранить кадр.", true);
            }
            return;
        }
        savePresetAvatar();
    });

    cropSaveButton?.addEventListener("click", () => saveButton?.click());

    cropImage?.addEventListener("load", () => {
        fitCropImage();
        resetCropPosition();
    });

    zoomInput?.addEventListener("input", () => {
        cropZoom = Number.parseFloat(zoomInput.value || "1");
        applyCropPosition();
    });

    cropStage?.addEventListener("pointerdown", (event) => {
        if (!pendingFile) return;
        isDraggingCrop = true;
        dragStartX = event.clientX - cropX;
        dragStartY = event.clientY - cropY;
        cropStage.setPointerCapture(event.pointerId);
    });

    cropStage?.addEventListener("pointermove", (event) => {
        if (!isDraggingCrop) return;
        cropX = event.clientX - dragStartX;
        cropY = event.clientY - dragStartY;
        applyCropPosition();
    });

    cropStage?.addEventListener("pointerup", (event) => {
        isDraggingCrop = false;
        cropStage.releasePointerCapture(event.pointerId);
    });

    cropStage?.addEventListener("pointercancel", () => {
        isDraggingCrop = false;
    });

    window.addEventListener("resize", fitCropImage);

    input.addEventListener("change", () => {
        const file = input.files && input.files[0];
        if (!file) return;
        if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
            showStatus("Разрешены только JPG, PNG и WebP.", true);
            input.value = "";
            return;
        }
        if (file.size > 5 * 1024 * 1024) {
            showStatus("Файл больше 5 МБ.", true);
            input.value = "";
            return;
        }
        pendingFile = file;
        selectedPresetId = "";
        hasAvatarChanges = true;
        choiceButtons.forEach((choice) => choice.classList.remove("is-selected"));
        if (selectedLabel) selectedLabel.textContent = "Выбрано: 0";
        if (pendingObjectUrl) URL.revokeObjectURL(pendingObjectUrl);
        pendingObjectUrl = URL.createObjectURL(file);
        if (cropImage) cropImage.src = pendingObjectUrl;
        setModalPreview(pendingObjectUrl);
        showPanel("crop");
        updateAvatarSaveState();
    });

    presetForm?.addEventListener("submit", (event) => {
        event.preventDefault();
        savePresetAvatar();
    });

    if (window.location.hash === "#profile-avatar-modal") {
        window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
        openAvatarModal();
    }

    updateAvatarSaveState();
})();

(() => {
    const root = document.querySelector(".profile-page");
    if (!root || !root.querySelector("[data-profile-social]")) return;

    const loadJQuery = () => {
        if (window.jQuery) return Promise.resolve(window.jQuery);

        return new Promise((resolve, reject) => {
            let script = document.querySelector("script[data-profile-jquery]");
            if (!script) {
                script = document.createElement("script");
                script.src = "https://code.jquery.com/jquery-3.7.1.min.js";
                script.dataset.profileJquery = "true";
                script.async = true;
                document.head.appendChild(script);
            }
            script.addEventListener("load", () => {
                if (window.jQuery) resolve(window.jQuery);
                else reject(new Error("jQuery не загрузился."));
            }, { once: true });
            script.addEventListener("error", () => reject(new Error("Не удалось загрузить jQuery.")), { once: true });
        });
    };

    const initSocialAjax = ($) => {
        const csrf = () => {
            const cookie = document.cookie.split(";").map((item) => item.trim()).find((item) => item.startsWith("csrftoken="));
            return cookie ? decodeURIComponent(cookie.slice("csrftoken=".length)) : "";
        };

        const requestSocial = ($block, { append = false } = {}) => {
            const $form = $block.find("[data-profile-social-form]");
            const url = $block.data("profile-social-url");
            const payload = $form.serializeArray();
            payload.push({ name: "offset", value: append ? ($block.attr("data-profile-social-next-offset") || 0) : 0 });

            $block.addClass("is-updating");
            return $.ajax({
                url,
                method: "GET",
                data: $.param(payload),
                dataType: "json",
                headers: { "X-Requested-With": "XMLHttpRequest" },
            }).done((response) => {
                if (!response?.ok) return;
                const $results = $block.find("[data-profile-social-results]");
                if (append) $results.append(response.html);
                else $results.html(response.html);

                $block.attr("data-profile-social-next-offset", response.next_offset || 0);
                $block.attr("data-profile-social-has-more", response.has_more ? "true" : "false");

                const remaining = Math.max(0, Number(response.total || 0) - Number(response.next_offset || 0));
                const $more = $block.find("[data-profile-social-more]");
                $more.prop("hidden", !response.has_more);
                $more.find("[data-profile-social-more-count]").text(String(remaining));

                Object.entries(response.metrics || {}).forEach(([key, value]) => {
                    $block.find(`[data-profile-social-metric="${key}"]`).each(function updateMetric() {
                        const prefix = this.hasAttribute("data-profile-social-signed") ? "+" : "";
                        $(this).text(`${prefix}${value}`);
                    });
                    $block.find(`[data-profile-social-count="${key}"]`).text(value);
                });
            }).always(() => {
                $block.removeClass("is-updating");
            });
        };

        $("[data-profile-social]").each(function initBlock() {
            const $block = $(this);
            let timer = null;

            $block.on("submit", "[data-profile-social-form]", (event) => {
                event.preventDefault();
                requestSocial($block);
            });

            $block.on("input", "[data-profile-social-search]", () => {
                window.clearTimeout(timer);
                timer = window.setTimeout(() => requestSocial($block), 220);
            });

            $block.on("change", "[data-profile-social-sort]", () => {
                requestSocial($block);
            });

            $block.on("click", "[data-profile-social-filter]", function onFilterClick() {
                const filter = this.dataset.profileSocialFilter || "all";
                $block.find("[data-profile-social-filter]").removeClass("is-active");
                $(this).addClass("is-active");
                $block.find("[data-profile-social-filter-input]").val(filter);
                requestSocial($block);
            });

            $block.on("click", "[data-profile-social-more]", () => {
                requestSocial($block, { append: true });
            });

            $block.on("click", "[data-follow-url]", function onFollowClick(event) {
                event.preventDefault();
                const button = this;
                if (button.disabled) return;
                const $button = $(button);
                const original = $button.text();
                button.disabled = true;
                $button.text("Подписываем...");
                $.ajax({
                    url: button.dataset.followUrl,
                    method: "POST",
                    dataType: "json",
                    headers: {
                        "X-CSRFToken": csrf(),
                        "X-Requested-With": "XMLHttpRequest",
                    },
                }).done((response) => {
                    if (!response?.ok) {
                        $button.text(response?.error || "Ошибка");
                        window.setTimeout(() => {
                            button.disabled = false;
                            $button.text(original);
                        }, 1600);
                        return;
                    }
                    $button.addClass("is-muted").removeAttr("data-follow-url").html("<span aria-hidden=\"true\">✓</span><span>Вы подписаны</span>");
                }).fail(() => {
                    $button.text("Ошибка");
                    window.setTimeout(() => {
                        button.disabled = false;
                        $button.text(original);
                    }, 1600);
                });
            });
        });
    };

    loadJQuery()
        .then(initSocialAjax)
        .catch((error) => console.error(error));
})();

(() => {
    const page = document.querySelector(".profile-page");
    if (!page) return;

    const escapeHtml = (value) => String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");

    const wireRow = (row, url) => {
        if (!row || !url) return;
        row.classList.add("is-profile-link");
        row.tabIndex = 0;
        row.dataset.profileUrl = url;
        row.addEventListener("click", (event) => {
            if (event.target.closest("a, button, input, label")) return;
            window.location.href = url;
        });
        row.addEventListener("keydown", (event) => {
            if (event.key === "Enter") window.location.href = url;
        });
    };

    const followersList = page.querySelector('[data-profile-list="followers"]');
    if (followersList) {
        followersList.querySelectorAll("[data-profile-username]").forEach((row) => {
            const username = row.dataset.profileUsername || "";
            if (!username) return;
            const url = `/cabinet/users/${encodeURIComponent(username)}/`;
            wireRow(row, url);
            const disabled = row.querySelector(".profile-row-action[disabled]");
            if (disabled) {
                const link = document.createElement("a");
                link.className = "profile-user-open";
                link.href = url;
                link.textContent = "Открыть профиль";
                disabled.replaceWith(link);
            }
        });
    }

    const followingList = page.querySelector('[data-profile-list="following"]');
    if (!followingList) return;

    fetch("/cabinet/profile/following/summary/", {
        credentials: "same-origin",
        cache: "no-store",
        headers: { "X-Requested-With": "XMLHttpRequest" },
    })
        .then((response) => response.ok ? response.json() : null)
        .then((payload) => {
            if (!payload?.ok) return;
            const byUsername = new Map((payload.items || []).map((item) => [String(item.username).toLowerCase(), item]));
            followingList.querySelectorAll("[data-profile-username]").forEach((row) => {
                const item = byUsername.get((row.dataset.profileUsername || "").toLowerCase());
                if (!item) return;
                const avatar = item.avatar_url
                    ? `<div class="profile-user-avatar"><img src="${escapeHtml(item.avatar_url)}" alt=""></div>`
                    : `<div class="profile-user-avatar">${escapeHtml(item.display_name || item.username).slice(0, 1).toUpperCase()}</div>`;
                const verified = item.is_verified ? '<span class="profile-user-verified">Проверен</span>' : "";
                const hasNewPredictions = Number.parseInt(item.new_predictions_count, 10) > 0;
                const newPredictionMeta = hasNewPredictions
                    ? `<div class="profile-user-meta">
                        <span class="profile-new-prediction-badge">Новый прогноз</span>
                        ${item.latest_new_prediction_label ? `<span>${escapeHtml(item.latest_new_prediction_label)}</span>` : ""}
                    </div>`
                    : "";
                row.dataset.profileHasNew = hasNewPredictions ? "true" : "false";
                row.classList.toggle("has-new-prediction", hasNewPredictions);
                row.innerHTML = `
                    ${avatar}
                    <div class="profile-user-copy">
                        <strong>${escapeHtml(item.display_name || item.username)}</strong>
                        <span>@${escapeHtml(item.username)}${item.specialization ? ` · ${escapeHtml(item.specialization)}` : ""}</span>
                        <div class="profile-user-meta">
                            <span>${escapeHtml(item.predictions_count)} прогнозов</span>
                            <span>${escapeHtml(item.followers_count)} подписчиков</span>
                            ${verified}
                        </div>
                        ${newPredictionMeta}
                    </div>
                    <a class="profile-user-open" href="${escapeHtml(item.url)}">Открыть профиль</a>`;
                wireRow(row, item.url);
            });
            const newCount = followingList.querySelectorAll('[data-profile-has-new="true"]').length;
            const filterButton = page.querySelector('[data-profile-new-filter="following"]');
            if (filterButton) {
                filterButton.disabled = newCount === 0 && !filterButton.classList.contains("is-active");
                const count = filterButton.querySelector("[data-profile-new-filter-count]");
                if (count) count.textContent = String(newCount);
            }
            window.CappersProfileApplyListFilters?.("following");
        })
        .catch(() => {});
})();

(() => {
    const page = document.querySelector(".profile-page");
    const tabs = page?.querySelector(".profile-tabs");
    if (!page || !tabs || page.querySelector('[data-profile-tab-panel="achievements"]')) return;

    const escapeHtml = (value) => String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");

    const achievementIconUrl = (item) => {
        if (item?.icon_url) return String(item.icon_url);
        if (item?.icon) return `/static/${String(item.icon).replace(/^\/+/, "")}`;
        return "";
    };

    const currentTab = () => new URL(window.location.href).searchParams.get("tab") || "profile";

    const activate = (panel, tab) => {
        page.querySelectorAll("[data-profile-tab-panel]").forEach((item) => item.classList.remove("is-active"));
        tabs.querySelectorAll("a").forEach((item) => item.classList.remove("is-active"));
        panel.classList.add("is-active");
        tab.classList.add("is-active");
    };

    const deactivate = (panel, tab) => {
        panel.classList.remove("is-active");
        tab.classList.remove("is-active");
    };

    fetch("/cabinet/profile/achievements/", {
        credentials: "same-origin",
        cache: "no-store",
        headers: { "X-Requested-With": "XMLHttpRequest" },
    })
        .then((response) => response.ok ? response.json() : null)
        .then((payload) => {
            if (!payload?.ok || payload.is_analyst) return;

            const tab = document.createElement("a");
            tab.href = `${window.location.pathname}?tab=achievements`;
            tab.textContent = "Достижения";
            tab.dataset.readerAchievementTab = "";
            tabs.insertBefore(tab, tabs.querySelector('a[href*="tab=following"]') || null);

            const cards = (payload.items || []).map((item) => `
                <article class="profile-achievement-card${item.unlocked ? " is-unlocked" : " is-locked"}" data-achievement="${escapeHtml(item.key)}">
                    <div class="profile-achievement-topline">
                        <span class="profile-achievement-icon"><img src="${escapeHtml(achievementIconUrl(item))}" alt=""></span>
                        <span class="profile-achievement-state${item.unlocked ? " is-unlocked" : ""}">${item.unlocked ? "Получено" : `${escapeHtml(item.progress)}%`}</span>
                    </div>
                    <span class="profile-achievement-category">${escapeHtml(item.category)}</span>
                    <h3>${escapeHtml(item.label)}</h3>
                    <p>${escapeHtml(item.description)}</p>
                    <div class="profile-achievement-progress"><i style="width: ${Number(item.progress) || 0}%"></i></div>
                    <div class="profile-achievement-meta"><span>Сейчас: ${escapeHtml(item.current_label)}</span><strong>Цель: ${escapeHtml(item.target_label)}</strong></div>
                </article>`).join("");

            const next = payload.next_achievement
                ? `<article class="profile-next-achievement">
                    <span class="profile-next-achievement-icon"><img src="${escapeHtml(achievementIconUrl(payload.next_achievement))}" alt=""></span>
                    <div><span>Ближайшая ачивка</span><strong>${escapeHtml(payload.next_achievement.label)}</strong><small>${escapeHtml(payload.next_achievement.description)}</small></div>
                    <div class="profile-next-achievement-progress"><strong>${escapeHtml(payload.next_achievement.progress)}%</strong><span>${escapeHtml(payload.next_achievement.current_label)} / ${escapeHtml(payload.next_achievement.target_label)}</span></div>
                </article>`
                : '<article class="profile-next-achievement is-complete"><div><span>Коллекция завершена</span><strong>Все достижения получены</strong></div></article>';

            const panel = document.createElement("section");
            panel.className = "profile-tab-panel";
            panel.dataset.profileTabPanel = "achievements";
            panel.id = "profile-tab-achievements";
            panel.innerHTML = `
                <div class="profile-achievements-shell">
                    <div class="profile-achievements-head">
                        <div><p class="eyebrow">Ваш прогресс</p><h2>Достижения</h2><p>Ачивки за лайки и сохранённые прогнозы.</p></div>
                        <div class="profile-achievements-total"><strong>${escapeHtml(payload.unlocked_count)}/${escapeHtml(payload.total_count)}</strong><span>получено</span></div>
                    </div>
                    <div class="profile-achievements-overall"><div><span>Общий прогресс</span><strong>${escapeHtml(payload.completion_percent)}%</strong></div><div class="profile-achievements-track"><i style="width: ${Number(payload.completion_percent) || 0}%"></i></div></div>
                    ${next}
                    <div class="profile-achievements-grid">${cards}</div>
                </div>`;

            const followingPanel = page.querySelector('[data-profile-tab-panel="following"]');
            page.insertBefore(panel, followingPanel || null);

            tab.addEventListener("click", (event) => {
                event.preventDefault();
                const url = new URL(tab.href, window.location.href);
                window.history.pushState({}, "", url);
                activate(panel, tab);
            });

            tabs.querySelectorAll("a:not([data-reader-achievement-tab])").forEach((link) => {
                link.addEventListener("click", () => deactivate(panel, tab));
            });

            window.addEventListener("popstate", () => {
                if (currentTab() === "achievements") activate(panel, tab);
                else deactivate(panel, tab);
            });

            if (currentTab() === "achievements") activate(panel, tab);
        })
        .catch(() => {});
})();


(() => {
    const buttons = Array.from(
        document.querySelectorAll("[data-profile-daily-task-claim]")
    );
    if (!buttons.length) return;

    const summary = document.querySelector(
        "[data-profile-daily-tasks-summary]"
    );

    const getCookie = (name) => {
        const item = document.cookie
            .split(";")
            .map((value) => value.trim())
            .find((value) => value.startsWith(`${name}=`));
        return item
            ? decodeURIComponent(item.slice(name.length + 1))
            : "";
    };

    const claimTask = async (button) => {
        if (button.disabled) return;

        const url = String(button.dataset.url || "");
        const card = button.closest(".profile-daily-tasks-card");
        const status = card?.querySelector("[data-profile-daily-task-status]");
        if (!url) return;

        const defaultLabel = button.textContent;
        button.disabled = true;
        button.textContent = button.dataset.pendingLabel || "Получаем…";
        if (status) status.textContent = "";

        try {
            const response = await fetch(url, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    Accept: "application/json",
                    "X-CSRFToken": getCookie("csrftoken"),
                },
            });
            const payload = await response.json().catch(() => null);
            if (!response.ok || !payload?.ok) {
                throw new Error(
                    payload?.error || "Не удалось получить награду."
                );
            }

            if (summary) {
                summary.textContent = String(
                    payload.daily_tasks_card?.summary_label || ""
                );
            }
            card?.querySelectorAll("[data-profile-daily-task-id]").forEach((row) => {
                row.classList.remove("is-in-progress");
                row.classList.add("is-completed");
                const check = row.querySelector(".profile-daily-task-check");
                if (check) check.textContent = "✓";
            });
            button.remove();
        } catch (error) {
            button.disabled = false;
            button.textContent = defaultLabel;
            if (status) {
                status.textContent = error instanceof Error
                    ? error.message
                    : button.dataset.errorLabel || "Не удалось получить награду.";
            }
        }
    };

    buttons.forEach((button) => {
        button.addEventListener("click", () => claimTask(button));
    });
})();
