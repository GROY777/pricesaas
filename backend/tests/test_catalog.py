import asyncio
import io
import os
import openpyxl
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@localhost/test')
os.environ.setdefault('JWT_SECRET', 'test-secret-at-least-thirty-two-characters-long')
from app.database import Base
from app.models import Tenant, Product
from app.routers import catalog

def test_catalog_isolation_pagination_export_and_delete():
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            a=Tenant(email='a@example.test',password_hash='x',company_name='A',api_key='a')
            b=Tenant(email='b@example.test',password_hash='x',company_name='B',api_key='b')
            db.add_all([a,b]); await db.flush()
            db.add_all([Product(tenant_id=a.id,name=f'Item {i}',barcode=f'A{i}',price=0 if i%2 else 10,unit='pc') for i in range(60)])
            db.add(Product(tenant_id=b.id,name='Secret',barcode='S',price=10,unit='pc')); await db.commit()
            result=await catalog.listing(q='',filter='all',page=2,limit=50,tenant=a,db=db)
            assert result['total']==60 and len(result['items'])==10
            assert (await catalog.listing(q='A1',filter='no_price',page=1,limit=50,tenant=a,db=db))['total']>0
            no_code = await catalog.create(catalog.ProductForm(article='sku-only',barcode=None,name='No barcode',price=0,unit='pc'),a,db)
            filtered = await catalog.listing(q='sku-only',filter='no_barcode',page=1,limit=50,tenant=a,db=db)
            assert filtered['total'] == 1 and filtered['items'][0]['id'] == no_code['id']
            response=await catalog.export(a,db); content=b''
            async for chunk in response.body_iterator: content+=chunk
            sheet=openpyxl.load_workbook(io.BytesIO(content)).active
            assert sheet.max_row==62 and 'Secret' not in str(list(sheet.values))
            ids=[result['items'][0]['id']]
            assert (await catalog.delete_selected(catalog.Selection(ids=ids),b,db))['deleted']==0
            assert (await catalog.delete_selected(catalog.Selection(ids=ids),a,db))['deleted']==1
        await engine.dispose()
    asyncio.run(run())
