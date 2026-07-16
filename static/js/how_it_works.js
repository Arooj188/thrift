(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        var steps = document.querySelectorAll('.hiw-step');
        var parties = document.querySelectorAll('.hiw-party');
        var allCards = [].concat(steps, parties);

        if ('IntersectionObserver' in window) {
            var observer = new IntersectionObserver(function (entries, obs) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting) {
                        entry.target.classList.add('is-visible');
                        obs.unobserve(entry.target);
                    }
                });
            }, { threshold: 0.1, rootMargin: '0px 0px -5% 0px' });

            allCards.forEach(function (card, i) {
                card.style.transitionDelay = (i * 80) + 'ms';
                observer.observe(card);
            });
        } else {
            allCards.forEach(function (card) {
                card.classList.add('is-visible');
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

        var internalLinks = document.querySelectorAll('a[href^="#"]');
        internalLinks.forEach(function (link) {
            link.addEventListener('click', function (e) {
                var id = link.getAttribute('href').slice(1);
                if (!id) { return; }
                var target = document.getElementById(id);
                if (target) {
                    e.preventDefault();
                    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            });
        });
    });
})();
