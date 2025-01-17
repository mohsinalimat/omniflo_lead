# Copyright (c) 2022, Omniflo and contributors
# For license information, please see license.txt


import frappe
import requests
import pprint
import json
from dateutil import parser
import pprint
from datetime import datetime
from frappe.model.document import Document

class DayWiseSales(Document):
	pass

@frappe.whitelist(allow_guest=True)
def run_day_sales():
	frappe.enqueue(day_sales,queue="long")


def day_sales():
	gmv_data=calculate_gmv()
	
	frappe.db.sql("""TRUNCATE TABLE `tabDay Wise Sales`;""")
	frappe.db.commit()
	
	for i in gmv_data:
		doc=frappe.new_doc('Day Wise Sales')
		doc.date=datetime.strptime(i[0], '%d-%m-%y')
		doc.customer=i[1]
		doc.qty=i[2]
		doc.item_code=i[3]
		doc.sale_from=i[4]
		doc.age=i[5]
		doc.gender=i[6]
		doc.save(ignore_permissions=True)
	frappe.db.commit()
	
@frappe.whitelist(allow_guest=True)
def calculate_gmv():

	def process_data():
		tx = []
		items = set()
		stores = set()
		def process_promoter():
			promoter_data=frappe.db.sql("""select psc.customer,psc.brand,psc.qty,psc.creation as date,psc.item_code,psc.item_name,psc.age,psc.gender  from `tabPromoter Sales Capture` as psc where psc.item_code is not null  order by psc.creation""",as_dict=True)
			entries = promoter_data
			#{'brand': 'Brawny Bear', 'customer': 'bangalore-rice-traders', 'date': '2022-10-20 22:40:14.433979', 'item_name': 'Date Sugar 200g', 'item_code': 'OMNI-ITM-BBR-078', 'qty': 2.0}
			for entry in entries:
				
				entry['event_type']='promoter'
				entry['dt'] = entry['date']
				tx.append(entry)


		def process_invoice():
		
			sales_data=frappe.db.sql("""select ADDTIME(CONVERT(si.posting_date, DATETIME), si.posting_time) as date,i.brand,si.customer as customer,sii.qty,i.item_name,i.mrp,i.item_code,null as gender,null as age from `tabSales Invoice` as si join `tabSales Invoice Item` as sii on sii.parent=si.name join `tabItem` as i on i.item_code=sii.item_code 
					where si.`status` != 'Cancelled' and si.`status`!="Draft" order by si.posting_date;""",as_dict=True)
			entries = sales_data
			#{'date': '2022-05-30 15:34:34', 'brand': 'Spice Story', 'customer': 'Royal villas super market', 'qty': 2.0, 'item_name': 'Schezwan Chutney', 'mrp': '125'}
			for entry in entries:
				dt = entry['date']
				entry['event_type']='invoice'
				entry['dt'] = dt
				tx.append(entry)
				items.add((entry['brand'], entry['item_name'], float(entry['mrp'])))
				stores.add(entry['customer'])

		def process_audit():

			audit_data=frappe.db.sql("""select al.posting_date as date,al.customer,ali.current_available_qty as qty,i.item_code,i.item_name,i.mrp,i.brand,null as gender,null as age from `tabAudit Log` as al join `tabAudit Log Items` as ali on ali.parent=al.name join `tabItem` as i on i.item_code=ali.item_code 
					where al.docstatus=1 order by al.posting_date;""",as_dict=True)
			entries =audit_data
			#{'date': '2021-11-29 00:00:00', 'customer': 'Nut Berry Akshay Nagar', 'qty': 1.0, 'item_name': 'Rage Coffee 50GMS Chai Latte', 'mrp': '349', 'brand': 'Rage Coffee'}
			for entry in entries:
				dt = entry['date']
				entry['event_type']='audit'
				entry['dt'] = dt
				tx.append(entry)


		process_promoter()
		process_invoice()
		process_audit()
		tx = sorted(tx, key=lambda d: d['dt']) 
		return items, stores, tx

	def stock_position():
		items, stores, txs = process_data()
		stock = {}
		for tx in txs:
			if tx['event_type'] == 'invoice' :
				customer, brand, item, qty, date ,age ,gender= tx['customer'], tx['brand'], tx['item_code'], tx['qty'], tx['dt'] ,tx['age'] ,tx['gender']
				if customer not in stock:
					stock[customer] = {}
				# if brand not in stock[customer]:
				#     stock[customer][brand] = {}
				if item not in stock[customer]:
					stock[customer][item] = []
				if not stock[customer][item]:
					stock[customer][item].append({'date':date, 'billed_qty': qty, 'current_qty': qty, 'cumulative_sales': 0, 'event_type': 'invoice','age':age,'gender':gender})
				else:
					current_qty = qty + stock[customer][item][-1]['current_qty']
					billed_qty = qty + stock[customer][item][-1]['billed_qty']
					cumulative_sales = billed_qty - current_qty
					if current_qty < 0:
						cumulative_sales = billed_qty
					stock[customer][item].append({'date':date, 'billed_qty': billed_qty, 'current_qty': current_qty, 'cumulative_sales': cumulative_sales,'event_type': 'invoice','age':age,'gender':gender})		
			
			if tx['event_type'] == 'audit' :
				customer, brand, item, qty, date ,age ,gender = tx['customer'], tx['brand'], tx['item_code'], tx['qty'], tx['dt'] ,tx['age'] ,tx['gender']
				if customer not in stock:
					stock[customer] = {}
				# if brand not in stock[customer]:
				#     stock[customer][brand] = {}
				if item not in stock[customer]:
					stock[customer][item] = []
				if not stock[customer][item]:
					stock[customer][item].append({'date':date, 'billed_qty': 0, 'current_qty': qty, 'cumulative_sales': 0, 'event_type': 'audit','age':age,'gender':gender})
				else:
					billed_qty = stock[customer][item][-1]['billed_qty']
					current_qty = qty
					cumulative_sales = billed_qty - current_qty
					if current_qty < 0:
						cumulative_sales = billed_qty	
					stock[customer][item].append({'date':date, 'billed_qty': billed_qty, 'current_qty': current_qty,'cumulative_sales': cumulative_sales, 'event_type': 'audit','age':age,'gender':gender})

			
			if tx['event_type'] == 'promoter' :
				customer, brand, item, qty, date ,age, gender= tx['customer'], tx['brand'], tx['item_code'], tx['qty'], tx['dt'], tx['age'], tx['gender']
				
				if customer not in stock:
					continue
				if item not in stock[customer]:
					continue
				# if item not in stock[customer][brand]:
				#     continue
				if not stock[customer][item]:
					continue
				else:
					billed_qty = (stock[customer][item][-1]['billed_qty'])
					current_qty = (stock[customer][item][-1]['current_qty']) - (qty)
					cumulative_sales = billed_qty - current_qty
					if current_qty < 0:
						cumulative_sales = billed_qty
					stock[customer][item].append({'date':date, 'billed_qty': billed_qty, 'current_qty': current_qty, 'cumulative_sales': cumulative_sales, 'event_type': 'promoter','age':age,'gender':gender})
		
		return stock, items

	@frappe.whitelist(allow_guest=True)
	def calculate_sales():
		sale_events = []
		stock, items = stock_position()
		for customer in stock:
			for sku in stock[customer]:
				item = stock[customer][sku]
				min_possible_sales = item[-1]['cumulative_sales']
				for i in range(len(item)-1, 0, -1): #python reverse loop until second last element
					if min_possible_sales > item[i-1]['cumulative_sales'] and min_possible_sales > 0 and item[i-1]['cumulative_sales']>=0:
						sales = min_possible_sales - item[i-1]['cumulative_sales']
						min_possible_sales = item[i-1]['cumulative_sales']
						date, event_type = item[i]['date'], item[i]['event_type']
						age,gender = item[i]['age'],item[i]['gender']
						sale_events.append((date, customer, sales, sku, event_type,age,gender))
		sale_events = sorted(sale_events, key=lambda d: d[0]) 
		for i in range(len(sale_events)):
			sale_events[i]=list(sale_events[i])
			sale_events[i][0]=sale_events[i][0].strftime("%d-%m-%y")
		return sale_events
	return json.loads(json.dumps(calculate_sales(),default=str))