import random
from collections import defaultdict
from typing import Any, TypeVar

import faker
import sqlalchemy as sa
from faker import Faker
from sqlalchemy import inspect

from database import Base
from database import sync_engine as engine
from models import Order, Product, Review, User

Faker.seed(10)
fake = Faker()


T = TypeVar("T")

with engine.connect() as conn:
    inspector = inspect(conn)
    meta = sa.MetaData()
    tables = []
    for table in inspector.get_table_names():
        tables.append(sa.Table(table, meta, autoload_with=engine))


def generate_users(model: type[User], amount: int = 100):
    table: sa.Table = model.__table__
    columns = list(table.columns)
    attributes = model.__dict__
    filtered_attributes = {}
    for attr_name, attr_value in attributes.items():
        if not attr_name.startswith("_"):  # Avoid internal attributes
            filtered_attributes[attr_name] = attr_value
    return model


def generate_products(model: type[Product], amount: int = 100):
    table: sa.Table = model.__table__
    columns = list(table.columns)
    attributes = model.__dict__
    filtered_attributes = {}
    for attr_name, attr_value in attributes.items():
        if not attr_name.startswith("_"):  # Avoid internal attributes
            filtered_attributes[attr_name] = attr_value
    return model


def generate_orders(model: type[Order], amount: int = 100):
    table: sa.Table = model.__table__
    attributes = model.__dict__
    filtered_attributes = {}
    for attr_name, attr_value in attributes.items():
        if not attr_name.startswith("_"):  # Avoid internal attributes
            filtered_attributes[attr_name] = attr_value
    return model


def create_DAG(models: list[type[Base]]) -> list[tuple[type[Base], list[type[Base]]]]:
    """Create order of what model needs to be created first"""
    model_names = {}
    dependent_on = defaultdict(list)
    for model in models:
        model_names[model.__table__.name] = model

        attributes = model.__dict__
        for attr_name, attr_value in attributes.items():
            if not attr_name.startswith("_"):  # Avoid internal attributes
                # We have a column or relationship
                if hasattr(attr_value, "foreign_keys"):
                    for fk in attr_value.foreign_keys:
                        dependency_name = fk.target_fullname.split(".")[0]
                        dependent_on[model].append((attr_name, dependency_name))

    sorted_order = []
    visited = set()
    visiting = set()

    def dfs_visit(model: type[Base]):
        """Recursively visit all dependencies of a model."""
        if model in visited:
            return
        if model in visiting:
            raise Exception(f"Circular dependency detected involving model: {model.__name__}")

        visiting.add(model)

        for dep in dependent_on.get(model, []):
            dep_model = dep[1]
            if isinstance(dep_model, str):
                dep_model = model_names[dep_model]
            dfs_visit(dep_model)

        visiting.remove(model)
        visited.add(model)
        temp = dependent_on[model]
        temp2 = []
        for t in temp:
            temp2.append((t[0], model_names[t[1]]))
        sorted_order.append((model, temp2))

    for model in models:
        if model not in visited:
            dfs_visit(model)

    return sorted_order


created_models: dict[type[Any], list[Any]] = defaultdict(list)

# Mapper between sqlalchemy dtypes and faker functions
faker_mapper = {
    # (method_name, kwargs_dict)
    sa.String: ("words", {}),
    sa.Text: ("paragraph", {"nb_sentences": 3}),
    sa.Integer: ("random_int", {"min": 1, "max": 10000}),
    sa.BigInteger: ("random_int", {"min": 100000, "max": 999999999}),
    sa.SmallInteger: ("random_int", {"min": 1, "max": 100}),
    sa.Float: ("pyfloat", {}),
    sa.Numeric: ("pydecimal", {"left_digits": 5, "right_digits": 2, "positive": True}),
    sa.Date: ("date_object", {}),
    sa.DateTime: ("date_time_this_decade", {}),
    sa.Time: ("time_object", {}),
    sa.Boolean: ("boolean", {}),
    sa.UUID: ("uuid4", {}),
}


def generate_model(model_input: tuple[type[Base], list[type[Base]]], amount: int) -> None:
    """
    Generates a specified number of instances for a given model.
    """
    # Clear the history of unique values for this generation batch.
    # This prevents UniquenessExceptions if you call the function multiple times.
    model = model_input[0]
    dependencies_mapping = {m[0]: m[1] for m in model_input[1]}
    fake.unique.clear()

    for i in range(amount):
        data = {}
        for col in model.__table__.columns:
            if col.name in dependencies_mapping:
                dependent_model = dependencies_mapping[col.name]
                random_index = random.randint(0, len(created_models[dependent_model]) - 1)
                data[col.name] = created_models[dependent_model][random_index].id

            else:
                faker_func = get_mapper_f(col, i)
                if faker_func:
                    try:
                        data[col.name] = faker_func()
                    except faker.exceptions.UniquenessException:
                        # This happens if Faker runs out of unique values to generate.
                        print(f"⚠️ Warning: Could not generate a unique value for {model.__name__}.{col.name}. Stopping generation for this model. Try requesting a smaller amount.")
                        return  # Exit the function for this model

        instance = model(**data)
        created_models[model].append(instance)


def get_mapper_f(col: sa.Column, number: int):
    """
    Gets the appropriate Faker function for a given column,
    respecting the unique constraint.
    """
    # Don't generate values for primary keys or auto-incrementing columns
    if col.primary_key or col.autoincrement == True:
        return lambda: number

    # Determine the provider: `fake.unique` for unique columns, otherwise `fake`
    provider = fake.unique if col.unique else fake

    # --- Name-based heuristics (highest priority) ---
    col_name = col.name.lower()
    if "email" in col_name:
        return provider.email
    if "user_name" in col_name or "username" in col_name:
        return provider.user_name
    if "full_name" in col_name:
        return provider.name
    if "phone" in col_name:
        return provider.phone_number

    # --- Type-based fallback using the mapper ---
    col_type = type(col.type)
    if col_type in faker_mapper:
        method_name, kwargs = faker_mapper[col_type]
        method = getattr(provider, method_name)
        # Return a callable function that includes the arguments
        return lambda: method(**kwargs)

    return None


all_models = [Review, Product, User, Order]
sorted_models = create_DAG(all_models)
for model in sorted_models:
    generate_model(model, 100)
print(created_models)
