/**
 * PrimeBooks Analytics Tracker
 * Client-side event tracking
 */

(function() {
    'use strict';

    const AnalyticsTracker = {
        endpoint: '/analytics/api/track/',

        /**
         * Track custom event
         */
        trackEvent: function(category, action, label = '', value = null, metadata = {}) {
            const data = {
                category: category,
                action: action,
                label: label,
                value: value,
                url_path: window.location.pathname,
                page_title: document.title,
                metadata: metadata
            };

            // Send to server
            this.sendBeacon(data);
        },

        /**
         * Track button click
         */
        trackClick: function(buttonName, metadata = {}) {
            this.trackEvent('CLICK', buttonName, window.location.pathname, null, metadata);
        },

        /**
         * Track form submission
         */
        trackFormSubmit: function(formName, metadata = {}) {
            this.trackEvent('FORM', 'form_submit', formName, null, metadata);
        },

        /**
         * Track download
         */
        trackDownload: function(fileName, fileType = '') {
            this.trackEvent('DOWNLOAD', 'file_download', fileName, null, {
                file_type: fileType
            });
        },

        /**
         * Track scroll depth
         */
        trackScrollDepth: function(depth) {
            this.trackEvent('SCROLL', 'scroll_depth', window.location.pathname, depth);
        },

        /**
         * Track video interaction
         */
        trackVideo: function(action, videoName, metadata = {}) {
            this.trackEvent('VIDEO', action, videoName, null, metadata);
        },

        /**
         * Send data using sendBeacon API (non-blocking)
         */
        sendBeacon: function(data) {
            const blob = new Blob([JSON.stringify(data)], {
                type: 'application/json'
            });

            if (navigator.sendBeacon) {
                navigator.sendBeacon(this.endpoint, blob);
            } else {
                // Fallback to fetch
                fetch(this.endpoint, {
                    method: 'POST',
                    body: JSON.stringify(data),
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    keepalive: true
                }).catch(err => console.error('Analytics tracking failed:', err));
            }
        },

        /**
         * Initialize automatic tracking
         */
        init: function() {
            // Track outbound links
            this.trackOutboundLinks();

            // Track scroll depth
            this.trackScrollBehavior();

            // Track time on page
            this.trackTimeOnPage();
        },

        /**
         * Track outbound link clicks
         */
        trackOutboundLinks: function() {
            document.addEventListener('click', (e) => {
                const link = e.target.closest('a');
                if (!link) return;

                const href = link.href;
                if (!href) return;

                // Check if external link
                if (href.startsWith('http') && !href.includes(window.location.hostname)) {
                    this.trackEvent('CLICK', 'outbound_link', href);
                }
            });
        },

        /**
         * Track scroll depth milestones
         */
        trackScrollBehavior: function() {
            const milestones = [25, 50, 75, 100];
            const reached = new Set();

            window.addEventListener('scroll', () => {
                const scrollPercent = (window.scrollY + window.innerHeight) / document.body.scrollHeight * 100;

                milestones.forEach(milestone => {
                    if (scrollPercent >= milestone && !reached.has(milestone)) {
                        reached.add(milestone);
                        this.trackScrollDepth(milestone);
                    }
                });
            });
        },

        /**
         * Track time spent on page
         */
        trackTimeOnPage: function() {
            let startTime = Date.now();

            window.addEventListener('beforeunload', () => {
                const timeSpent = Math.floor((Date.now() - startTime) / 1000);
                this.trackEvent('ENGAGEMENT', 'time_on_page', window.location.pathname, timeSpent);
            });
        }
    };

    // Expose to global scope
    window.PrimeAnalytics = AnalyticsTracker;

    // Auto-initialize
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => AnalyticsTracker.init());
    } else {
        AnalyticsTracker.init();
    }

})();