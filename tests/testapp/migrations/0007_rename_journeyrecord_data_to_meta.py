from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("testapp", "0006_rename_collection_to_item_list"),
    ]

    operations = [
        migrations.RenameField(
            model_name="journeyrecord",
            old_name="data",
            new_name="meta",
        ),
    ]
