(function () {
    "use strict";

    var STORAGE_KEY = "relicSolverInputs";

    var button = document.getElementById("clearStorage");
    var status = document.getElementById("clearStorageStatus");
    if (!button || !status) return;

    function isStored() {
        try {
            return localStorage.getItem(STORAGE_KEY) !== null;
        } catch {

            return false;
        }
    }

    function render() {
        if (isStored()) {
            button.disabled = false;
            status.textContent = "Your last inputs are saved in this browser.";
        } else {
            button.disabled = true;
            status.textContent = "Nothing is saved in this browser.";
        }
    }

    button.hidden = false;
    render();

    button.addEventListener("click", function () {
        try {
            localStorage.removeItem(STORAGE_KEY);
        } catch {}
        button.disabled = true;
        status.textContent = "Saved inputs cleared.";
    });
})();
