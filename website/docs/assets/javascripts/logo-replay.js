/**
 * Logo GIF Replay Controller
 *
 * Plays the animated GIF logo for a set number of loops, then swaps to
 * a static PNG.  When the user scrolls or clicks AFTER the animation
 * has stopped, replays for another round.
 *
 * The logo img is tagged with data-logo-gif on first discovery so we
 * can always find it regardless of what its current src is.
 */
(function () {
    "use strict";

    // --- Configuration ---------------------------------------------------
    var LOOP_COUNT = 6;

    // Logo_TailWaggle.gif is ~2.1 seconds per loop.
    var SINGLE_LOOP_MS = 2100;
    var TOTAL_PLAY_MS = SINGLE_LOOP_MS * LOOP_COUNT;

    var GIF_PATH = "assets/images/logo_animated.gif";
    var STATIC_PATH = "assets/images/mca.png";

    // State
    var playing = false;
    var timer = null;
    var bound = false;

    /**
     * Find the logo img — first by our data attribute, then by src.
     * Tags it with data-logo-gif so future lookups always work
     * even after the src has been swapped to the static PNG.
     */
    function findLogo() {
        var img = document.querySelector("img[data-logo-gif]");
        if (img) return img;

        // First discovery — find by the gif or static src in the content area.
        var candidates = document.querySelectorAll(
            'img[src*="logo_animated"], img[src*="mca.png"]'
        );
        for (var i = 0; i < candidates.length; i++) {
            // Only tag the one inside page content, not the header logo.
            var parent = candidates[i].closest(".md-content");
            if (parent) {
                candidates[i].setAttribute("data-logo-gif", "1");
                return candidates[i];
            }
        }
        return null;
    }

    /**
     * Start the GIF for LOOP_COUNT cycles, then freeze.
     */
    function startAnimation(img) {
        if (playing) return;
        playing = true;

        // Cache-bust forces the browser to re-fetch and replay from frame 1.
        img.src = GIF_PATH + "?t=" + Date.now();

        clearTimeout(timer);
        timer = setTimeout(function () {
            img.src = STATIC_PATH;
            playing = false;
        }, TOTAL_PLAY_MS);
    }

    /**
     * Interaction handler — only triggers replay after animation has stopped.
     */
    function onInteraction() {
        if (playing) return;
        var img = findLogo();
        if (img) startAnimation(img);
    }

    /**
     * Bind interaction listeners once.
     * Uses scroll and click only — mousemove is too noisy.
     */
    function bindEvents() {
        if (bound) return;
        bound = true;

        ["scroll", "click", "touchstart"].forEach(function (evt) {
            document.addEventListener(evt, onInteraction, { passive: true });
        });
    }

    /**
     * Initialize: find the logo, start animation, bind events.
     */
    function init() {
        var img = findLogo();
        if (!img) return;

        startAnimation(img);
        bindEvents();
    }

    // Run on initial load.
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    // Re-init on MkDocs Material instant navigation.
    document.addEventListener("DOMContentSwitch", init);
})();
