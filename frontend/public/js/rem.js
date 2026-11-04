(function (win) {
    var doc = win.document;
    var docEl = doc.documentElement;
    var resizeTimer;

    function syncRem() {
        var width = docEl.getBoundingClientRect().width;
        if (width > 1920) {
            width = 1920;
        }
        var rem = width / 19.2;
        docEl.style.fontSize = rem + 'px';
    }

    win.addEventListener('resize', function () {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(syncRem, 300);
    }, false);
    win.addEventListener('pageshow', function (e) {
        if (e.persisted) {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(syncRem, 300);
        }
    }, false);
    syncRem();
})(window);
