var $j = jQuery.noConflict();
var AttributeSearch = {};

AttributeSearch.search = function () {
  var q = $j('#attrQuery').val();
  var showValues = $j('#showValues').is(':checked');
  $.getJSON('/api/attributes/search', { q: q, showValues: showValues }, function (rows) {
    AttributeSearch.render(rows, showValues);
  });
};

AttributeSearch.render = function (rows, showValues) {
  var columns = [{ data: 'id', title: 'ID' }, { data: 'name', title: 'Name' }];
  if (showValues) {
    columns.push({ data: 'value', title: 'Value' });
  }
  new Handsontable(document.getElementById('attributeGrid'), { data: rows, columns: columns, readOnly: true });
};

$j(document).ready(function () {
  $('#searchButton').click(AttributeSearch.search);
  $j('#clearSearchButton').on('click', function () {
    $j('#attrQuery').val('');
    $j('#attributeGrid').empty();
  });
  $j('#showValues').on('change', AttributeSearch.search);
});
