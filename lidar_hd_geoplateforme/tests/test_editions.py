import unittest
try:
    from lidar_hd_geoplateforme.core import Record,grouped,build_jobs,latest_coverage,resource_date,tile_key
except ImportError:  # QGIS absent : exécuter avec le Python de QGIS
    Record=None
@unittest.skipIf(Record is None,'qgis indisponible')
class Tests(unittest.TestCase):
    def setUp(self):
        self.records=[
          Record('newA','https://x/IP_2025-04-10/LHD_FXX_0543_6329_PTS.copc.laz','2026-07-10','LAMB93','IGN69','0543-6329','2025-04-10'),
          Record('oldA','https://x/IP_2024-01-01/LHD_FXX_0543_6329_PTS.copc.laz','2025-04-10','LAMB93','IGN69','0543-6329','2024-01-01'),
          Record('newB','https://x/IP_2026-07-10/LHD_FXX_0544_6329_PTS.copc.laz','2026-07-10','LAMB93','IGN69','0544-6329','2026-07-10')]
    def test_latest_is_per_tile(self):
        selected=latest_coverage(self.records);self.assertEqual([r.id for r in selected],['newA','newB'])
    def test_latest_job_is_not_single_catalogue_group(self):
        jobs=build_jobs(self.records,1,'');self.assertEqual(jobs[0][0],'couverture_plus_recente');self.assertEqual(jobs[0][2],'latest_per_tile')
    def test_resource_date_is_distinct(self):self.assertEqual(resource_date(self.records[0].url),'2025-04-10')
    def test_exact_edition_stays_exact(self):
        jobs=build_jobs(self.records,2,'2025-04-10');self.assertEqual([r.id for r in jobs[0][1]],['oldA'])
