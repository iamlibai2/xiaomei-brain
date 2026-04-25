from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///inventory.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# 商品模型
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    sku = db.Column(db.String(50), unique=True, nullable=False)
    category = db.Column(db.String(50))
    description = db.Column(db.Text)
    quantity = db.Column(db.Integer, default=0)
    min_stock = db.Column(db.Integer, default=10)  # 库存预警阈值
    unit_price = db.Column(db.Float, default=0.0)
    supplier = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    @property
    def is_low_stock(self):
        return self.quantity <= self.min_stock

    @property
    def total_value(self):
        return self.quantity * self.unit_price

# 库存记录模型
class StockTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)  # 'in' or 'out'
    quantity = db.Column(db.Integer, nullable=False)
    reference = db.Column(db.String(100))  # 订单号或备注
    created_at = db.Column(db.DateTime, default=datetime.now)

    product = db.relationship('Product', backref='transactions')

# 初始化数据库
def init_db():
    with app.app_context():
        db.create_all()

# 路由 - 首页
@app.route('/')
def index():
    products = Product.query.all()
    total_products = len(products)
    total_value = sum(p.total_value for p in products)
    low_stock_count = sum(1 for p in products if p.is_low_stock)

    return render_template('index.html',
                         products=products,
                         total_products=total_products,
                         total_value=total_value,
                         low_stock_count=low_stock_count)

# 路由 - 商品列表
@app.route('/products')
def product_list():
    search = request.args.get('search', '')
    category = request.args.get('category', '')

    query = Product.query

    if search:
        query = query.filter(
            (Product.name.like(f'%{search}%')) |
            (Product.sku.like(f'%{search}%'))
        )

    if category:
        query = query.filter(Product.category == category)

    products = query.order_by(Product.updated_at.desc()).all()
    categories = db.session.query(Product.category).distinct().all()
    categories = [c[0] for c in categories if c[0]]

    return render_template('product_list.html',
                         products=products,
                         categories=categories,
                         search=search,
                         selected_category=category)

# 路由 - 添加商品
@app.route('/product/new', methods=['GET', 'POST'])
def product_new():
    if request.method == 'POST':
        product = Product(
            name=request.form['name'],
            sku=request.form['sku'],
            category=request.form.get('category', ''),
            description=request.form.get('description', ''),
            quantity=int(request.form['quantity']),
            min_stock=int(request.form['min_stock']),
            unit_price=float(request.form['unit_price']),
            supplier=request.form.get('supplier', '')
        )

        try:
            db.session.add(product)
            db.session.commit()
            flash('商品添加成功！', 'success')

            # 如果初始数量大于0，创建入库记录
            if product.quantity > 0:
                transaction = StockTransaction(
                    product_id=product.id,
                    transaction_type='in',
                    quantity=product.quantity,
                    reference='初始库存'
                )
                db.session.add(transaction)
                db.session.commit()

            return redirect(url_for('product_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'添加失败：{str(e)}', 'error')

    return render_template('product_form.html', product=None)

# 路由 - 编辑商品
@app.route('/product/<int:id>/edit', methods=['GET', 'POST'])
def product_edit(id):
    product = Product.query.get_or_404(id)

    if request.method == 'POST':
        product.name = request.form['name']
        product.sku = request.form['sku']
        product.category = request.form.get('category', '')
        product.description = request.form.get('description', '')
        product.quantity = int(request.form['quantity'])
        product.min_stock = int(request.form['min_stock'])
        product.unit_price = float(request.form['unit_price'])
        product.supplier = request.form.get('supplier', '')

        try:
            db.session.commit()
            flash('商品更新成功！', 'success')
            return redirect(url_for('product_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败：{str(e)}', 'error')

    return render_template('product_form.html', product=product)

# 路由 - 删除商品
@app.route('/product/<int:id>/delete', methods=['POST'])
def product_delete(id):
    product = Product.query.get_or_404(id)

    try:
        db.session.delete(product)
        db.session.commit()
        flash('商品删除成功！', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败：{str(e)}', 'error')

    return redirect(url_for('product_list'))

# 路由 - 库存操作
@app.route('/stock/<int:id>/transaction', methods=['GET', 'POST'])
def stock_transaction(id):
    product = Product.query.get_or_404(id)

    if request.method == 'POST':
        transaction_type = request.form['type']  # 'in' or 'out'
        quantity = int(request.form['quantity'])
        reference = request.form.get('reference', '')

        if quantity <= 0:
            flash('数量必须大于0', 'error')
            return render_template('stock_transaction.html', product=product)

        if transaction_type == 'out' and quantity > product.quantity:
            flash('出库数量不能超过当前库存！', 'error')
            return render_template('stock_transaction.html', product=product)

        try:
            # 更新库存
            if transaction_type == 'in':
                product.quantity += quantity
            else:
                product.quantity -= quantity

            # 创建交易记录
            transaction = StockTransaction(
                product_id=product.id,
                transaction_type=transaction_type,
                quantity=quantity,
                reference=reference
            )

            db.session.add(transaction)
            db.session.commit()
            flash('库存操作成功！', 'success')
            return redirect(url_for('product_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'操作失败：{str(e)}', 'error')

    return render_template('stock_transaction.html', product=product)

# 路由 - 库存记录
@app.route('/stock/records')
def stock_records():
    records = StockTransaction.query.order_by(
        StockTransaction.created_at.desc()
    ).limit(100).all()

    return render_template('stock_records.html', records=records)

# 路由 - 低库存预警
@app.route('/alerts/low-stock')
def low_stock_alerts():
    products = Product.query.filter(
        Product.quantity <= Product.min_stock
    ).all()

    return render_template('low_stock.html', products=products)

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)