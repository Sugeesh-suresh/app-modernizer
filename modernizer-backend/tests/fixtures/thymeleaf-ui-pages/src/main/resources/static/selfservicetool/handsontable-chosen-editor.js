(function (Handsontable) {
  var ChosenEditor = Handsontable.editors.TextEditor.prototype.extend();
  ChosenEditor.prototype.open = function () {
    this.$textarea.next().find("input").on("keydown", function (e) {
      e.preventDefault();
    });
    $("input").on("click", function (e) { e.preventDefault(); });
  };
})(Handsontable);
