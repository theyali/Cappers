from django.core.cache import cache
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from .context_processors import PAGE_CONTEXT_CACHE_VERSION_KEY
from .models import AdvBanner, PagePromoBanner, PageSEO, PromoBanner


def bump_page_context_cache_version(**kwargs):
    try:
        cache.incr(PAGE_CONTEXT_CACHE_VERSION_KEY)
    except Exception:
        try:
            cache.set(PAGE_CONTEXT_CACHE_VERSION_KEY, 2, timeout=None)
        except Exception:
            pass


for model in (PageSEO, PromoBanner, AdvBanner, PagePromoBanner):
    post_save.connect(
        bump_page_context_cache_version,
        sender=model,
        dispatch_uid=f"pages_{model.__name__.lower()}_seo_cache_save",
    )
    post_delete.connect(
        bump_page_context_cache_version,
        sender=model,
        dispatch_uid=f"pages_{model.__name__.lower()}_seo_cache_delete",
    )


@receiver(m2m_changed, sender=PageSEO.adv_banners.through)
@receiver(m2m_changed, sender=PageSEO.promo_banners.through)
def page_seo_m2m_changed(**kwargs):
    bump_page_context_cache_version()
