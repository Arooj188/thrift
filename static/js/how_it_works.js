(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        var cards = document.querySelectorAll('.hiw-card');
        var faqs = document.querySelectorAll('.hiw-faq-item');
        var allItems = [].concat(cards, faqs);

        function showItem(item, index) {
            item.style.transitionDelay = (index * 80) + 'ms';
            item.classList.add('is-visible');
        }

        if ('IntersectionObserver' in window) {
            var observer = new IntersectionObserver(function (entries, obs) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting) {
                        var index = allItems.indexOf(entry.target);
                        showItem(entry.target, index >= 0 ? index : 0);
                        obs.unobserve(entry.target);
                    }
                });
            }, { threshold: 0.1, rootMargin: '0px 0px -5% 0px' });

            allItems.forEach(function (item, i) {
                var rect = item.getBoundingClientRect();
                if (rect.top < window.innerHeight && rect.bottom > 0) {
                    showItem(item, i);
                } else {
                    observer.observe(item);
                }
            });
        } else {
            allItems.forEach(function (item, i) {
                showItem(item, i);
            });
        }

        var ctaBtn = document.querySelector('.hiw-cta a.btn-sell');
        if (ctaBtn) {
            ctaBtn.addEventListener('mouseenter', function () {
                ctaBtn.classList.add('hiw-btn-hover');
            });
            ctaBtn.addEventListener('mouseleave', function () {
                ctaBtn.classList.remove('hiw-btn-hover');
            });
        }
    });
})();
