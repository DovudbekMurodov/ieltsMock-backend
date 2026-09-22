from django.db import migrations

from apps.grading.band_scales import NOTES, SCALES


def create_scales(apps, schema_editor):
    BandScale = apps.get_model("grading", "BandScale")
    BandScaleRow = apps.get_model("grading", "BandScaleRow")

    for name, skill, rows in SCALES:
        scale, _ = BandScale.objects.update_or_create(
            name=name,
            skill=skill,
            defaults={"raw_total": 40, "is_default": True, "notes": NOTES},
        )
        BandScaleRow.objects.filter(scale=scale).delete()
        BandScaleRow.objects.bulk_create(
            BandScaleRow(scale=scale, raw_min=lo, raw_max=hi, band=band)
            for lo, hi, band in rows
        )


def drop_scales(apps, schema_editor):
    BandScale = apps.get_model("grading", "BandScale")
    BandScale.objects.filter(name__in=[name for name, _, _ in SCALES]).delete()


class Migration(migrations.Migration):
    dependencies = [("grading", "0001_initial")]

    operations = [migrations.RunPython(create_scales, drop_scales)]
