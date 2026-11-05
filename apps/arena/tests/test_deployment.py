"""Deployment failure injection: systemd/git are mocked, SQLite backup is real."""
import importlib.util
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import arena as core
from operations import inspect_db

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
def load_script(name):
    spec=importlib.util.spec_from_file_location(name,SCRIPTS/(name+'.py'))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

deploy=load_script('deploy_release')
preflight=load_script('preflight')
prune=load_script('prune_logs')


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.path=self.root/'live_v03_bitvavo.sqlite3'
        self.con=core.open_db(str(self.path))
        self.events=[]

    def tearDown(self):
        self.con.close()
        self.temp.cleanup()

    def command(self,*args,**kwargs):
        self.events.append(args)
        if args[:2]==('git','rev-parse'):return 'old-sha'
        return ''

    def exercise(self,health=None):
        with patch.object(deploy,'command',side_effect=self.command), \
             patch.object(deploy,'active',return_value=True), \
             patch.object(deploy,'digest',return_value='unchanged-config'), \
             patch.object(deploy,'install_units',side_effect=lambda:self.events.append(('install-units',))), \
             patch.object(deploy,'wait_live',side_effect=health):
            deploy.deploy('new-sha',self.root,self.root/'candidate',port=8787)

    def test_update_stops_before_backup_and_keeps_database(self):
        original=deploy.backup_database
        def snapshot(*args,**kwargs):
            self.assertIn(('sudo','systemctl','stop',deploy.SERVICE),self.events)
            self.assertNotIn(('git','checkout','--detach','new-sha'),self.events)
            self.events.append(('backup',))
            return original(*args,**kwargs)
        before=inspect_db(self.path)
        with patch.object(deploy,'backup_database',side_effect=snapshot):self.exercise()
        self.assertEqual(inspect_db(self.path),before)
        self.assertEqual(len(list((self.root/'pre-update').glob('*.sqlite3'))),1)
        self.assertLess(self.events.index(('backup',)),self.events.index(('git','checkout','--detach','new-sha')))
        self.assertEqual(self.events[-1],('sudo','systemctl','start',deploy.TIMER))

    def test_failed_new_service_restores_code_but_preserves_new_history(self):
        def health(*_):
            if ('git','checkout','--detach','old-sha') not in self.events:
                core.log(self.con,'Synthetic post-update audit event')
                raise TimeoutError('simulated unhealthy release')
        with self.assertRaises(TimeoutError):self.exercise(health)
        self.assertIn(('git','checkout','--detach','old-sha'),self.events)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM logs').fetchone()[0],1)
        self.assertEqual(self.events.count(('install-units',)),2)

    def test_failed_backup_prevents_new_code_checkout(self):
        with patch.object(deploy,'backup_database',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.exercise()
        self.assertNotIn(('git','checkout','--detach','new-sha'),self.events)
        self.assertIn(('sudo','systemctl','start',deploy.SERVICE),self.events)

    def test_candidate_tests_do_not_receive_credentials(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test','ANTHROPIC_API_KEY':'test','LLM_TRADING_ARENA_DATA_DIR':'live'}):
            env=deploy.clean_test_env()
        self.assertNotIn('OPENAI_API_KEY',env)
        self.assertNotIn('ANTHROPIC_API_KEY',env)
        self.assertNotIn('LLM_TRADING_ARENA_DATA_DIR',env)

    def test_preflight_refuses_unsynchronized_clock_before_database_access(self):
        with patch.object(preflight,'load_dotenv'), \
             patch.object(preflight.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stdout='no\n')), \
             patch.object(preflight,'inspect_db') as check:
            with self.assertRaises(RuntimeError):preflight.check()
            check.assert_not_called()

    def test_log_retention_preserves_recent_logs_and_portfolios(self):
        with self.con:
            self.con.execute("INSERT INTO logs(ts,level,message) VALUES ('2000-01-01T00:00:00+00:00','INFO','old')")
        core.log(self.con,'current')
        prune.prune(self.path)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM logs').fetchone()[0],1)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM portfolios').fetchone()[0],7)

    def test_cli_missing_live_database_fails_without_creating_history(self):
        data=self.root/'empty'
        env=dict(os.environ,LLM_TRADING_ARENA_DATA_DIR=str(data),OPENAI_API_KEY='',ANTHROPIC_API_KEY='')
        result=subprocess.run([sys.executable,'main.py','start'],env=env,capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((data/'live_v03_bitvavo.sqlite3').exists())

    def test_cli_explicit_initialization_never_overwrites_existing_history(self):
        data=self.root/'new'
        env=dict(os.environ,LLM_TRADING_ARENA_DATA_DIR=str(data),OPENAI_API_KEY='',ANTHROPIC_API_KEY='')
        first=subprocess.run([sys.executable,'main.py','init-live'],env=env,capture_output=True,timeout=10)
        self.assertEqual(first.returncode,0)
        before=inspect_db(data/'live_v03_bitvavo.sqlite3')
        second=subprocess.run([sys.executable,'main.py','init-live'],env=env,capture_output=True,timeout=10)
        self.assertNotEqual(second.returncode,0)
        self.assertEqual(inspect_db(data/'live_v03_bitvavo.sqlite3'),before)
        self.assertFalse((data/'demo_v03_bitvavo.sqlite3').exists())


if __name__=='__main__':unittest.main()
