{% test dbt_utils_unique_combo(model, cols) %}
select {{ cols | join(', ') }}, count(*) from {{ model }} group by all having count(*) > 1
{% endtest %}
