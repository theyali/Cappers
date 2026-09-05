(function ($) {
    "use strict";

    if (!$) return;

    $(function () {
        $(document).on("change", "[data-bot-row] .avatar-upload-input", function () {
            const input = this;
            const file = input.files && input.files[0];
            if (!file) return;

            const $input = $(input);
            const $row = $input.closest("[data-bot-row]");
            const $block = $input.closest("[data-bot-avatar-block]");
            const $avatar = $block.find("[data-bot-avatar-wrapper]").first();
            const $status = $block.find("[data-bot-avatar-status]").first();
            const uploadUrl = $row.attr("data-avatar-upload-url");
            const csrfToken = $row.find('input[name="csrfmiddlewaretoken"]').val();

            if (!uploadUrl || !csrfToken) {
                $status.text("Не удалось начать загрузку изображения.");
                input.value = "";
                return;
            }

            const formData = new FormData();
            formData.append("avatar", file);

            window.CappersSkeleton?.loading($block.get(0));
            $status.text("Загрузка изображения...");
            $input.prop("disabled", true);

            $.ajax({
                url: uploadUrl,
                method: "POST",
                data: formData,
                processData: false,
                contentType: false,
                dataType: "json",
                headers: {
                    "X-CSRFToken": csrfToken,
                },
            })
                .done(function (response) {
                    if (!response || !response.ok || !response.avatar_url) {
                        $status.text("Не удалось загрузить изображение.");
                        window.CappersSkeleton?.ready($block.get(0));
                        return;
                    }

                    let $image = $avatar.find("img").first();
                    if (!$image.length) {
                        $avatar.empty();
                        $image = $("<img>", {
                            width: 46,
                            height: 46,
                        });
                        $avatar.append($image);
                    }

                    const username = $row.find('input[name$="-username"]').val() || "бота";
                    $image.attr({
                        src: response.avatar_url,
                        alt: "Аватар " + username,
                        width: 46,
                        height: 46,
                    });

                    window.CappersSkeleton?.ready($block.get(0));
                    window.CappersSkeleton?.watchImage($avatar.get(0));
                    $status.text(response.message || "Изображение обновлено.");
                })
                .fail(function (xhr) {
                    const response = xhr.responseJSON || {};
                    $status.text(response.error || "Не удалось загрузить изображение.");
                    window.CappersSkeleton?.ready($block.get(0));
                })
                .always(function () {
                    input.value = "";
                    $input.prop("disabled", false);
                });
        });
    });
})(window.jQuery);
