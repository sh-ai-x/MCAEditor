/**
 * Downloads Page — Dynamic Renderer
 *
 * Fetches /releases.json and renders download tables, changelog,
 * and previous versions into the static download.md skeleton.
 *
 * Dependencies: None (vanilla JS).
 */
(function () {
    "use strict";

    var RELEASES_URL = "/releases.json";
    var DOWNLOAD_BASE = "/downloads/maya/";
    var DOWNLOAD_BASE_UE = "/downloads/unreal/";

    // Python versions per Maya year (for the table display).
    var MAYA_PYTHON = {
        "2024": "3.10",
        "2025": "3.11",
        "2026": "3.11"
    };

    // -----------------------------------------------------------------------
    // Tab switching
    // -----------------------------------------------------------------------

    /**
     * Initialize tab click handlers within a tab group.
     */
    function initTabs(tabsContainerId) {
        var container = document.getElementById(tabsContainerId);
        if (!container) return;

        var tabs = container.querySelectorAll(".dl-tab");
        tabs.forEach(function (tab) {
            tab.addEventListener("click", function () {
                // Deactivate all siblings.
                tabs.forEach(function (t) { t.classList.remove("active"); });
                tab.classList.add("active");

                // Show/hide the matching content panels.
                var parent = container.parentElement;
                var panels = parent.querySelectorAll(".dl-tab-content");
                panels.forEach(function (p) { p.classList.remove("active"); });

                var target = document.getElementById(tab.getAttribute("data-target"));
                if (target) target.classList.add("active");
            });
        });
    }

    // -----------------------------------------------------------------------
    // Table builders
    // -----------------------------------------------------------------------

    /**
     * Build an HTML download table for Maya.
     *
     * @param {Object} files — e.g. {"2024": "filename.zip", "2025": ...}
     * @param {string} basePath — URL prefix for download links
     * @param {string} platform — "Windows" or "macOS"
     * @return {string} HTML table markup
     */
    function buildMayaTable(files, basePath, platform) {
        if (!files || !Object.keys(files).length) return "<p>No downloads available.</p>";

        var html = '<table class="dl-table">';
        html += "<thead><tr><th>Maya Version</th><th>Python</th><th></th></tr></thead><tbody>";

        var years = Object.keys(files).sort();
        years.forEach(function (year) {
            var url = basePath + files[year];
            var pyVer = MAYA_PYTHON[year] || "3.11";
            html += "<tr>";
            html += "<td>Maya " + year + "</td>";
            html += "<td>Python " + pyVer + "</td>";
            html += '<td><a href="' + url + '" class="md-button md-button--primary"' +
                ' data-umami-event="download"' +
                ' data-umami-event-product="Maya ' + year + '"' +
                ' data-umami-event-platform="' + platform + '"' +
                ' data-umami-event-file="' + files[year] + '"' +
                '>Download</a></td>';
            html += "</tr>";
        });

        html += "</tbody></table>";
        return html;
    }

    /**
     * Build an HTML download table for Unreal Engine.
     *
     * @param {Object} files — e.g. {"5.4": "filename.zip", "5.5": ...}
     * @param {string} basePath — URL prefix for download links
     * @return {string} HTML table markup
     */
    function buildUETable(files, basePath) {
        if (!files || !Object.keys(files).length) return "<p>No downloads available.</p>";

        var html = '<table class="dl-table">';
        html += "<thead><tr><th>UE Version</th><th></th></tr></thead><tbody>";

        var versions = Object.keys(files).sort();
        versions.forEach(function (ver) {
            var url = basePath + files[ver];
            html += "<tr>";
            html += "<td>Unreal Engine " + ver + "</td>";
            html += '<td><a href="' + url + '" class="md-button md-button--primary"' +
                ' data-umami-event="download"' +
                ' data-umami-event-product="UE ' + ver + '"' +
                ' data-umami-event-file="' + files[ver] + '"' +
                '>Download</a></td>';
            html += "</tr>";
        });

        html += "</tbody></table>";
        return html;
    }

    /**
     * Render changelog bullet list.
     */
    function buildChangelog(changes) {
        if (!changes || !changes.length) return "";

        var html = "<ul>";
        changes.forEach(function (item) {
            html += "<li>" + item + "</li>";
        });
        html += "</ul>";
        return html;
    }

    // -----------------------------------------------------------------------
    // Check if a DCC downloads section has any actual files
    // -----------------------------------------------------------------------

    function hasDownloads(dccDownloads) {
        if (!dccDownloads) return false;
        // Check if any platform has files.
        var platforms = Object.keys(dccDownloads);
        for (var i = 0; i < platforms.length; i++) {
            var files = dccDownloads[platforms[i]];
            if (files && Object.keys(files).length > 0) return true;
        }
        return false;
    }

    // -----------------------------------------------------------------------
    // Main render
    // -----------------------------------------------------------------------

    function render(data) {
        var releases = data.releases || [];
        if (!releases.length) {
            document.getElementById("dl-loading").textContent =
                "No releases available yet. Check back soon.";
            return;
        }

        var latest = releases[0];

        // Hide loading, show content.
        document.getElementById("dl-loading").style.display = "none";
        document.getElementById("dl-content").style.display = "block";

        // Version badge.
        var badge = document.getElementById("dl-badge");
        badge.innerHTML =
            '<span style="background:#E8922A; color:#fff; padding:4px 12px; border-radius:4px; ' +
            'font-weight:600; font-size:0.9em;">v' + latest.version + "</span>" +
            ' <span style="color:#888; margin-left:8px;">Released ' + latest.date + "</span>";

        // --- Maya downloads ---
        var maya = latest.downloads && latest.downloads.maya;
        if (maya) {
            var winEl = document.getElementById("dl-maya-win");
            var macEl = document.getElementById("dl-maya-mac");
            if (winEl) winEl.innerHTML = buildMayaTable(maya.windows, DOWNLOAD_BASE, "Windows");
            if (macEl) macEl.innerHTML = buildMayaTable(maya.macos, DOWNLOAD_BASE, "macOS");
        }

        // --- UE downloads ---
        var ue = latest.downloads && latest.downloads.unreal;
        var ueWrapper = document.getElementById("dl-ue-wrapper");
        if (hasDownloads(ue)) {
            // Show UE section and populate tables.
            if (ueWrapper) ueWrapper.style.display = "block";
            var ueWin = document.getElementById("dl-ue-win");
            var ueMac = document.getElementById("dl-ue-mac");
            if (ueWin) ueWin.innerHTML = buildUETable(ue.windows, DOWNLOAD_BASE_UE);
            if (ueMac) ueMac.innerHTML = buildUETable(ue.macos, DOWNLOAD_BASE_UE);
        } else {
            // Hide the entire UE section when no downloads exist.
            if (ueWrapper) ueWrapper.style.display = "none";
        }

        // --- What's New ---
        var changesEl = document.getElementById("dl-changes");
        if (changesEl) {
            changesEl.innerHTML = buildChangelog(latest.changelog);
        }

        // --- Previous versions ---
        if (releases.length > 1) {
            var prevEl = document.getElementById("dl-previous");
            if (prevEl) {
                var prevHtml = "";
                for (var i = 1; i < releases.length; i++) {
                    var rel = releases[i];
                    prevHtml += "<h4>v" + rel.version + " &mdash; " + rel.date + "</h4>";
                    prevHtml += buildChangelog(rel.changelog);

                    // Compact download links for previous versions.
                    var prevMaya = rel.downloads && rel.downloads.maya;
                    if (prevMaya) {
                        prevHtml += '<p class="dl-prev-links">';
                        if (prevMaya.windows) {
                            Object.keys(prevMaya.windows).sort().forEach(function (year) {
                                prevHtml += '<a href="' + DOWNLOAD_BASE + prevMaya.windows[year] +
                                    '">Maya ' + year + " Win</a> ";
                            });
                        }
                        if (prevMaya.macos) {
                            Object.keys(prevMaya.macos).sort().forEach(function (year) {
                                prevHtml += '<a href="' + DOWNLOAD_BASE + prevMaya.macos[year] +
                                    '">Maya ' + year + " Mac</a> ";
                            });
                        }
                        prevHtml += "</p>";
                    }
                }
                prevEl.innerHTML = prevHtml;
            }
        }

        // Initialize tab switching.
        initTabs("dl-maya-tabs");
        initTabs("dl-ue-tabs");
    }

    // -----------------------------------------------------------------------
    // Init
    // -----------------------------------------------------------------------

    function init() {
        // Only run on the download page.
        if (!document.getElementById("dl-loading")) return;

        fetch(RELEASES_URL)
            .then(function (resp) {
                if (!resp.ok) throw new Error("HTTP " + resp.status);
                return resp.json();
            })
            .then(render)
            .catch(function () {
                document.getElementById("dl-loading").textContent =
                    "Unable to load releases. Please try again later.";
            });
    }

    // Run on load.
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    // Support MkDocs Material instant navigation.
    document.addEventListener("DOMContentSwitch", init);
})();
