"""Each generation of the same company+role on the same day must get its own
output folder, so two runs never collide into one folder (which made the newer
run's download resolve to the older run's stale resume.vN files).

Regression for: running IMC twice (pre/post prompt change) wrote both into
output/<date>/IMC_Graduate_Software_Engineer, and the download resolver
(_latest_resume_version picks max vN) served the older run's tweaked resume.
"""
from src.main import _unique_job_folder


def test_returns_base_name_when_folder_absent(tmp_path):
    # First-ever generation: no suffix, unchanged behaviour.
    assert _unique_job_folder(tmp_path, "IMC_Grad") == tmp_path / "IMC_Grad"


def test_suffixes_when_base_folder_exists(tmp_path):
    (tmp_path / "IMC_Grad").mkdir()
    assert _unique_job_folder(tmp_path, "IMC_Grad") == tmp_path / "IMC_Grad_2"


def test_increments_past_multiple_existing(tmp_path):
    (tmp_path / "IMC_Grad").mkdir()
    (tmp_path / "IMC_Grad_2").mkdir()
    (tmp_path / "IMC_Grad_3").mkdir()
    assert _unique_job_folder(tmp_path, "IMC_Grad") == tmp_path / "IMC_Grad_4"
