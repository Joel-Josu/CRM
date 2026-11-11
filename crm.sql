CREATE DATABASE crm_ai;
USE crm_ai;

CREATE TABLE customers(
    customer_id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100),
    email VARCHAR(100),
    phone VARCHAR(20),
    city VARCHAR(50),
    state VARCHAR(50),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE products(
    product_id INT PRIMARY KEY AUTO_INCREMENT,
    product_name VARCHAR(100),
    category VARCHAR(50),
    price DECIMAL(10,2)
);

CREATE TABLE orders(
    order_id INT PRIMARY KEY AUTO_INCREMENT,
    customer_id INT,
    order_date DATE,
    total_amount DECIMAL(10,2),
    status VARCHAR(20),
    FOREIGN KEY(customer_id)
    REFERENCES customers(customer_id)
);

CREATE TABLE order_items(
    item_id INT PRIMARY KEY AUTO_INCREMENT,
    order_id INT,
    product_id INT,
    quantity INT,
    amount DECIMAL(10,2),
    FOREIGN KEY(order_id)
    REFERENCES orders(order_id),
    FOREIGN KEY(product_id)
    REFERENCES products(product_id)
);

CREATE TABLE leads(
    lead_id INT PRIMARY KEY AUTO_INCREMENT,
    lead_name VARCHAR(100),
    source VARCHAR(50),
    status VARCHAR(30),
    assigned_to VARCHAR(50)
);

CREATE TABLE employees(
    employee_id INT PRIMARY KEY AUTO_INCREMENT,
    employee_name VARCHAR(100),
    department VARCHAR(50),
    email VARCHAR(100)
);



INSERT INTO customers
(name,email,phone,city,state)
VALUES
('Arun','arun@gmail.com','9876543210','Kochi','Kerala'),
('Rahul','rahul@gmail.com','9876543211','Kochi','Kerala'),
('Anu','anu@gmail.com','9876543212','Thrissur','Kerala'),
('Priya','priya@gmail.com','9876543213','Calicut','Kerala'),
('John','john@gmail.com','9876543214','Bangalore','Karnataka'),
('Riya','riya@gmail.com','9876543215','Chennai','Tamil Nadu'),
('David','david@gmail.com','9876543216','Mumbai','Maharashtra'),
('Ajay','ajay@gmail.com','9876543217','Delhi','Delhi'),
('Sneha','sneha@gmail.com','9876543218','Pune','Maharashtra'),
('Vishnu','vishnu@gmail.com','9876543219','Kochi','Kerala'),
('Akhil','akhil@gmail.com','9876543220','Kollam','Kerala'),
('Meera','meera@gmail.com','9876543221','Kannur','Kerala'),
('Nikhil','nikhil@gmail.com','9876543222','Kochi','Kerala'),
('Ramesh','ramesh@gmail.com','9876543223','Mysore','Karnataka'),
('Hari','hari@gmail.com','9876543224','Palakkad','Kerala'),
('Neha','neha@gmail.com','9876543225','Hyderabad','Telangana'),
('Kiran','kiran@gmail.com','9876543226','Kochi','Kerala'),
('Deepa','deepa@gmail.com','9876543227','Thrissur','Kerala'),
('Manu','manu@gmail.com','9876543228','Kochi','Kerala'),
('Anjali','anjali@gmail.com','9876543229','Trivandrum','Kerala');


INSERT INTO products (product_name, category, price)
VALUES
('Laptop Pro','Electronics',75000),
('Gaming Laptop','Electronics',95000),
('Wireless Mouse','Accessories',1200),
('Mechanical Keyboard','Accessories',3500),
('Monitor 24 Inch','Electronics',12000),
('Monitor 27 Inch','Electronics',18000),
('USB Hub','Accessories',800),
('External SSD','Storage',6500),
('Printer','Office',9000),
('Scanner','Office',7000),
('Tablet','Electronics',25000),
('Smartphone','Electronics',30000),
('Router','Networking',2500),
('Webcam','Accessories',2200),
('Headset','Accessories',1800),
('Projector','Office',35000),
('Power Bank','Accessories',1500),
('Office Chair','Furniture',8500),
('Standing Desk','Furniture',22000),
('NAS Storage','Storage',45000);



INSERT INTO employees
(employee_name,department,email)
VALUES
('Arjun','Sales','arjun@crm.com'),
('Priya','Sales','priya@crm.com'),
('Rahul','Marketing','rahul@crm.com'),
('Anu','Support','anu@crm.com'),
('Vivek','IT','vivek@crm.com'),
('Meera','HR','meera@crm.com'),
('Akhil','Sales','akhil@crm.com'),
('Neha','Finance','neha@crm.com'),
('David','IT','david@crm.com'),
('Sneha','Support','sneha@crm.com'),
('John','Marketing','john@crm.com'),
('Riya','HR','riya@crm.com'),
('Kiran','Sales','kiran@crm.com'),
('Hari','Support','hari@crm.com'),
('Manu','Finance','manu@crm.com'),
('Deepa','Marketing','deepa@crm.com'),
('Anjali','Sales','anjali@crm.com'),
('Nikhil','IT','nikhil@crm.com'),
('Vishnu','Support','vishnu@crm.com'),
('Ramesh','Sales','ramesh@crm.com');


INSERT INTO leads
(lead_name,source,status,assigned_to)
VALUES
('Tech Solutions','Website','New','Arjun'),
('ABC Retail','LinkedIn','Contacted','Priya'),
('Future Systems','Referral','Qualified','Rahul'),
('Vision Tech','Website','New','Akhil'),
('Green Energy','Email','Contacted','Anjali'),
('Blue Ocean','LinkedIn','Lost','Kiran'),
('Data Minds','Referral','Qualified','Arjun'),
('Cloud Corp','Website','Won','Priya'),
('Quick Mart','Email','New','Rahul'),
('SoftEdge','LinkedIn','Contacted','Akhil'),
('NextGen','Referral','Qualified','Anjali'),
('Prime Tech','Website','Won','Kiran'),
('Star Retail','Email','Lost','Arjun'),
('Smart Systems','Website','New','Priya'),
('Innovate Ltd','LinkedIn','Contacted','Rahul'),
('Global Trade','Referral','Qualified','Akhil'),
('Fast Logistics','Website','Won','Anjali'),
('SecureNet','Email','Lost','Kiran'),
('Metro Stores','Website','New','Arjun'),
('Bright Future','Referral','Qualified','Priya');



INSERT INTO orders
(customer_id,order_date,total_amount,status)
VALUES
(1,'2026-06-01',75000,'Completed'),
(2,'2026-06-02',95000,'Completed'),
(3,'2026-06-03',1200,'Completed'),
(4,'2026-06-04',3500,'Pending'),
(5,'2026-06-05',12000,'Completed'),
(6,'2026-06-06',18000,'Completed'),
(7,'2026-06-07',800,'Pending'),
(8,'2026-06-08',6500,'Completed'),
(9,'2026-06-09',9000,'Completed'),
(10,'2026-06-10',7000,'Completed'),
(11,'2026-06-11',25000,'Pending'),
(12,'2026-06-12',30000,'Completed'),
(13,'2026-06-13',2500,'Completed'),
(14,'2026-06-14',2200,'Pending'),
(15,'2026-06-15',1800,'Completed'),
(16,'2026-06-16',35000,'Completed'),
(17,'2026-06-17',1500,'Completed'),
(18,'2026-06-18',8500,'Pending'),
(19,'2026-06-19',22000,'Completed'),
(20,'2026-06-20',45000,'Completed');



INSERT INTO order_items
(order_id,product_id,quantity,amount)
VALUES
(1,1,1,75000),
(2,2,1,95000),
(3,3,1,1200),
(4,4,1,3500),
(5,5,1,12000),
(6,6,1,18000),
(7,7,1,800),
(8,8,1,6500),
(9,9,1,9000),
(10,10,1,7000),
(11,11,1,25000),
(12,12,1,30000),
(13,13,1,2500),
(14,14,1,2200),
(15,15,1,1800),
(16,16,1,35000),
(17,17,1,1500),
(18,18,1,8500),
(19,19,1,22000),
(20,20,1,45000);