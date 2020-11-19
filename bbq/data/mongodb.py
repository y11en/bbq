from functools import wraps
from collections import namedtuple
import motor.motor_asyncio
from pymongo.errors import ServerSelectionTimeoutError, AutoReconnect
import time
import traceback
import pandas as pd
from bbq import log
from abc import ABC
import asyncio


class MongoDB(ABC):
    _MongoStat = namedtuple('_MongoStat', ['client', 'count', 'last'])

    def __init__(self, uri='mongodb://localhost:27017/', pool=5):
        self.log = log.get_logger(self.__class__.__name__)
        self.clients = []

        self.uri = uri
        self.pool = pool

    def _best_client(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            self.clients = sorted(self.clients, key=lambda stat: (stat.count, -stat.last))
            stat_client = self.clients[0]
            self.clients[0] = stat_client._replace(count=stat_client.count + 1, last=time.time())

            kwargs['__client'] = stat_client.client
            return func(self, *args, **kwargs)

        return wrapper

    def init(self):
        try:
            for _ in range(self.pool):
                client = motor.motor_asyncio.AsyncIOMotorClient(self.uri)
                self.clients.append(self._MongoStat(client=client, count=0, last=time.time()))
        except Exception as e:
            self.log.error('连接mongodb失败: uri={}, ex={}'.format(self.uri, e))
            return False

        return True

    @_best_client
    def get_client(self, **kwargs):
        return kwargs['__client'] if '__client' in kwargs else None

    async def do_load(self, coll, filter=None, projection=None, skip=0, limit=0, sort=None, to_frame=True):
        for i in range(5):
            try:
                cursor = coll.find(filter=filter, projection=projection, skip=skip, limit=limit, sort=sort)
                if cursor is not None:
                    # data = [await item async for item in cursor]
                    data = await cursor.to_list(None)
                    await cursor.close()
                    if to_frame:
                        df = pd.DataFrame(data=data, columns=projection)
                        if not df.empty:
                            if '_id' in df.columns:
                                df.drop(columns=['_id'], inplace=True)
                            return df
                    else:
                        if data is not None:
                            del data['_id']
                        return data
            except (ServerSelectionTimeoutError, AutoReconnect) as e:
                self.log.error('mongodb 调用 {}, 连接异常: ex={}, call {}, {}s后重试'.format(self.do_load.__name__,
                                                                                    e, traceback.format_exc(),
                                                                                    (i + 1) * 5))
                await asyncio.sleep((i + 1) * 5)
                self.init()
        return None

    async def do_update(self, coll, filter=None, update=None, upsert=True):
        for i in range(5):
            try:
                if update is None:
                    return None
                res = await coll.update_one(filter, {'$set': update}, upsert=upsert)
                return res.upserted_id
            except (ServerSelectionTimeoutError, AutoReconnect) as e:
                self.log.error('mongodb 调用 {}, 连接异常: ex={}, call {}, {}s后重试'.format(self.do_update.__name__,
                                                                                    e, traceback.format_exc(),
                                                                                    (i + 1) * 5))
                await asyncio.sleep((i + 1) * 5)
                self.init()
        return 0

    async def do_batch_update(self, data, func):
        upsert_list = []
        for item in data.to_dict('records'):
            coll, filter, update = func(item)
            upsert = await self.do_update(coll, filter=filter, update=update)
            if upsert is None:
                continue
            if isinstance(upsert, list):
                upsert_list = upsert_list + upsert
            else:
                upsert_list.append(upsert)
        return upsert_list if len(upsert_list) > 0 else None

    async def do_delete(self, coll, filter=None, just_one=True):
        for i in range(5):
            try:
                res = None
                if just_one:
                    res = await coll.delete_one(filter)
                else:
                    if filter is not None:
                        res = await coll.delete_many(filter)
                    else:
                        res = await coll.drop()
                return 0 if res is None else res.deleted_count
            except (ServerSelectionTimeoutError, AutoReconnect) as e:
                self.log.error('mongodb 调用 {}, 连接异常: ex={}, call {}, {}s后重试').format(self.do_delete.__name__,
                                                                                     e, traceback.format_exc(),
                                                                                     (i + 1) * 5)
                await asyncio.sleep((i + 1) * 5)
                self.init()
        return 0

    async def do_insert(self, coll, data):
        for i in range(5):
            try:
                inserted_ids = []
                if data is not None and not data.empty:
                    docs = data.to_dict('records')
                    result = await coll.insert_many(docs)
                    inserted_ids = result.inserted_ids
                return inserted_ids
            except (ServerSelectionTimeoutError, AutoReconnect) as e:
                self.log.error('mongodb 调用 {}, 连接异常: ex={}, call {}, {}s后重试').format(self.do_insert.__name__,
                                                                                     e, traceback.format_exc(),
                                                                                     (i + 1) * 5)
                await asyncio.sleep((i + 1) * 5)
                self.init()
        return 0