"""The durable example's tables, renamed with the vocabulary they model.

`Collection` became `AddAnother` in the library, and these are the example
of a database-backed store for one. Renames rather than a create-and-drop
pair, because a rename is what happened: the rows are the same rows.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("testapp", "0005_application")]

    operations = [
        # The constraints name the old model, so they go first and come back
        # at the end under the new names.
        migrations.RemoveConstraint(
            model_name="collectionrecord", name="unique_collection"
        ),
        migrations.RemoveConstraint(
            model_name="collectionitemrecord", name="unique_collection_item"
        ),
        migrations.RenameModel(old_name="CollectionRecord", new_name="ItemListRecord"),
        migrations.RenameModel(old_name="CollectionItemRecord", new_name="ItemRecord"),
        migrations.RenameField(
            model_name="itemrecord",
            old_name="collection_key",
            new_name="list_key",
        ),
        migrations.AlterField(
            model_name="itemlistrecord",
            name="owner",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="wizard_item_lists",
                to="auth.user",
            ),
        ),
        migrations.AlterField(
            model_name="itemrecord",
            name="owner",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="wizard_items",
                to="auth.user",
            ),
        ),
        migrations.AddConstraint(
            model_name="itemlistrecord",
            constraint=models.UniqueConstraint(
                fields=("owner", "journey", "key"), name="unique_item_list"
            ),
        ),
        migrations.AddConstraint(
            model_name="itemrecord",
            constraint=models.UniqueConstraint(
                fields=("owner", "journey", "list_key", "item_id"),
                name="unique_item",
            ),
        ),
    ]
