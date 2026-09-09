(() => {
    const forms = document.querySelectorAll("[data-required-submit-form]");

    forms.forEach((form) => {
        const submit = form.querySelector('button[type="submit"]');
        if (!submit) return;

        const requiredFields = Array.from(form.querySelectorAll("[required]")).filter((field) => {
            return !field.disabled && field.type !== "hidden";
        });

        const fieldIsFilled = (field) => {
            if (field.type === "checkbox" || field.type === "radio") {
                return field.checked;
            }
            return String(field.value || "").trim().length > 0;
        };

        const updateSubmit = () => {
            submit.disabled = requiredFields.some((field) => !fieldIsFilled(field));
        };

        requiredFields.forEach((field) => {
            field.addEventListener("input", updateSubmit);
            field.addEventListener("change", updateSubmit);
        });

        updateSubmit();
    });
})();
